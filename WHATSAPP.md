# WhatsApp in ABM CRM

ABM CRM has two WhatsApp modes. Switch between them in Settings → WhatsApp Templates.

| | Click to Chat (default) | Cloud API |
|---|---|---|
| Cost | Free | Template messages charged by Meta |
| Needs | Nothing; the rep's WhatsApp app or WhatsApp Web | Meta app + WhatsApp Business number, `frappe_whatsapp` |
| Sending | Opens WhatsApp with the message typed in, the rep presses send | Sent from inside the CRM |
| Replies | Stay in the rep's WhatsApp | Show up in the CRM |
| Templates | ABM WhatsApp Templates (any text, Jinja) | Meta-approved templates |

**Click to Chat:** the lead/deal WhatsApp tab shows your templates with the lead's details filled in.
Tap one, edit it, then tap **Open in WhatsApp**. Each message is logged on the record (ABM WhatsApp Log)
and in its activity feed. The WhatsApp button on leads, deals and mobile list rows opens the chat directly.

Unofficial tools that link a personal WhatsApp through WhatsApp Web (Baileys, whatsmeow, WAHA and
similar) can also send and receive for free. They break WhatsApp's terms of service, and numbers that
use them can be banned, so ABM CRM does not use them.

The rest of this guide covers the **Cloud API** mode.

CRM's WhatsApp tab (on leads and deals) uses the [frappe_whatsapp](https://github.com/shridarpatil/frappe_whatsapp)
app, which talks directly to Meta's **WhatsApp Cloud API**. There is no third-party provider in between.

- Installed on realtech: `frappe_whatsapp` 1.0.12 (branch `master`, supports Frappe up to v17).
- On a new site: `bench get-app https://github.com/shridarpatil/frappe_whatsapp --branch master`,
  then `bench --site <site> install-app frappe_whatsapp` and `bench --site <site> migrate`.
  The migrate step lets crm give Sales Users and Sales Managers access to WhatsApp messages and templates.

## How it works

- **Sending:** CRM creates a `WhatsApp Message` document. frappe_whatsapp sends it to the Graph API
  (`https://graph.facebook.com/<version>/<phone_id>/messages`) with your access token.
- **Receiving:** Meta calls a webhook on your site. frappe_whatsapp saves the message, and crm links it to the
  lead or deal with the same phone number and notifies the assigned users.
  Webhook URL: `https://<your-site>/api/method/frappe_whatsapp.utils.webhook.webhook`
- **Meta's rules:**
  - You can only *start* a conversation with an approved **template**.
  - Once the customer replies, a **24-hour window** opens. In that window you can send normal text and
    media for free.

## Cost

You do not need a paid Meta plan. The Cloud API has no monthly fee. Meta charges only for **template
messages that get delivered**. Prices below are approximate for India, per message:

| Message | Cost |
|---|---|
| Replies and normal messages inside the 24-hour window | Free |
| Utility template sent inside an open 24-hour window | Free |
| Utility or authentication template (outside the window) | about $0.0014 |
| Marketing template | about $0.0118 |
| Everything, for 72 hours after a click-to-WhatsApp ad or Facebook page CTA | Free |

- Meta's free **test number** costs nothing. It can message up to 5 phone numbers that you verify, with up to 250 messages a day.
- To message real customers from your own number, you need a payment method on the WhatsApp Business account.
  Business verification is also needed to raise sending limits.
- The test number has these limits:
  - It can only send approved templates, such as the built-in `hello_world`.
  - It can only send to the 5 phone numbers you verified.

## Test setup (free, about 20 minutes)

1. **Meta app:** go to https://developers.facebook.com → My Apps → Create App → type *Business* →
   add the **WhatsApp** product. Meta creates a test WhatsApp Business account and a test number.
2. **Your phone:** in WhatsApp → API Setup, add your own mobile number to the recipient list ("To") and
   verify it with the code Meta sends. You can add up to 5 numbers.
3. **Copy these values** from API Setup:
   - Temporary access token
   - Phone number ID
   - WhatsApp Business Account ID
   - App ID (from App settings → Basic)
4. **Permanent token:** the temporary token expires in 24 hours. For longer use, go to Meta Business Settings
   → Users → System Users → Add, assign the app and the WhatsApp account, then Generate token. Give it the
   permissions `whatsapp_business_messaging` and `whatsapp_business_management`.
5. **WhatsApp Account in Frappe:** in desk, go to `/app/whatsapp-account/new` and fill in:
   - Account Name: anything, e.g. `Test Number`
   - Token: the access token
   - URL: `https://graph.facebook.com`
   - Version: `v23.0`
   - Phone ID: the Phone number ID
   - Business ID: the WhatsApp Business Account ID
   - App ID: the App ID
   - Webhook Verify Token: any secret string you choose, e.g. `abm-wa-verify-2026`
   - Status: **Active**
   - Tick **Default Outgoing** and **Default Incoming**
6. **WhatsApp Settings:** open `/app/whatsapp-settings` and set the default outgoing account if it is empty.
   CRM shows the WhatsApp tab only when the default outgoing account is Active.
7. **Templates:** open `/app/whatsapp-templates` and click **Fetch from Meta**, so `hello_world` appears.
8. **Send a test:** open a lead whose mobile number is your verified phone, in international format
   (e.g. `+9198xxxxxxxx`). In the WhatsApp tab, pick the template `hello_world` and send it.

### Receiving replies (webhook)

Meta has to reach your site over public HTTPS, so a laptop on `localhost` needs a tunnel:

1. Start a free tunnel with Cloudflare, which needs no account. First install `cloudflared` from
   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/, then run:
   ```bash
   cloudflared tunnel --url http://localhost:8006
   ```
   It prints a URL like `https://random-words.trycloudflare.com`. That URL serves realtech, because realtech
   is this bench's default site.
2. In the Meta app, go to WhatsApp → Configuration → Webhook → Edit:
   - Callback URL: `https://random-words.trycloudflare.com/api/method/frappe_whatsapp.utils.webhook.webhook`
   - Verify token: the same Webhook Verify Token as in step 5
3. Click **Verify and save**, then **subscribe** to the `messages` field.
4. Reply to the test message from your phone. The reply shows up in the lead's WhatsApp tab, and the
   24-hour window is now open for free-text chat.

The quick-tunnel URL changes every time you restart cloudflared, so update the callback URL in Meta each time.
On a server with a real domain, use that domain instead.

## Phone numbers and common errors

abm_crm converts the recipient to the full international number before sending, so a lead saved as
`9876543210` is sent to `919876543210`. Numbers without a country code use **Default Phone Region**
in ABM CRM Settings (`/app/abm-crm-settings`, default `IN`). Meta's errors are shown in plain words:

| Meta code | Meaning | Fix |
|---|---|---|
| 131030 | Recipient not on the test number's allowed list | Meta app > WhatsApp > API Setup > "To": add and verify the number |
| 131047 | 24-hour window closed | Send a template instead of free text |
| 132000 | Wrong number of template variables | Check the template's `{{1}}`, `{{2}}` |
| 131026 | Message undeliverable | Number may not be on WhatsApp |
| 190 | Access token expired | Create a new token (System User token lasts) and update the WhatsApp Account |

## Known gaps (to fix in abm_crm)

- **No template variables:** crm's `send_whatsapp_template` does not pass template parameters, so templates
  with variables (`{{1}}`) can't be filled in from the CRM UI. `hello_world` has no variables, so testing works.
- **No window warning:** there is no warning when the 24-hour window is closed. Free text sent outside it fails
  on Meta's side.
- **One number for everyone:** all messages go out from the single default account. There is no routing of
  numbers per sales rep.
- **Unknown numbers:** messages from numbers that aren't on any lead are not turned into new leads.
