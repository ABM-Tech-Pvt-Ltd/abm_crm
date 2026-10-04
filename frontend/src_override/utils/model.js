// abm_crm: copy of crm's utils/model.js with Tags (_user_tags) added to the standard fields,
// so it can be picked as a list column (rendered as chips in Leads/DealsListView).
export const standardFieldsMeta = [
  {
    fieldname: 'name',
    label: 'Name',
    fieldtype: 'Data',
  },
  {
    fieldname: 'creation',
    label: 'Created On',
    fieldtype: 'Datetime',
  },
  {
    fieldname: 'modified',
    label: 'Last Modified',
    fieldtype: 'Datetime',
  },
  {
    fieldname: 'modified_by',
    label: 'Modified By',
    fieldtype: 'Link',
    options: 'User',
  },
  { label: 'Assigned To', fieldtype: 'Text', fieldname: '_assign' },
  {
    label: 'Owner',
    fieldtype: 'Link',
    fieldname: 'owner',
    options: 'User',
  },
  { label: 'Like', fieldtype: 'Data', fieldname: '_liked_by' },
  // abm_crm: record tags
  { label: 'Tags', fieldtype: 'Data', fieldname: '_user_tags' },
]

export const noValueFieldTypes = [
  'Section Break',
  'Column Break',
  'Tab Break',
  'Table',
  'Table MultiSelect',
  'Button',
  'Image',
]
