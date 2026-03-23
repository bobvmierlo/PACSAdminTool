HL7 Template Files
==================
Each .hl7 file in this folder is loaded automatically by the tool at startup.
You can add, edit or delete files here without changing any code.

FILE FORMAT
-----------
Lines starting with # are metadata or comments and are ignored when sending.

Two special metadata lines are recognised:
  # name: <display name shown in the dropdown>
  # description: <tooltip/help text>

All other lines are the HL7 message body. Use carriage returns (CR, \r) as
segment separators — the tool handles this automatically; just write one
segment per line in your text editor.

PLACEHOLDER SUBSTITUTION
------------------------
Use {placeholder} syntax anywhere in the message body. The tool will
substitute these from the quick-fill fields when you click "Load Template".

Standard placeholders (always available):
  {ts}              Current timestamp  (YYYYMMDDHHmmss)
  {msgid}           Unique message control ID
  {pid}             Patient ID
  {name}            Patient name  (LAST^FIRST)
  {name_last}       Family name part only
  {name_first}      Given name part only
  {dob}             Date of birth  (YYYYMMDD)
  {sex}             Sex  (M / F / U)
  {acc}             Accession number
  {proc_code}       Procedure code
  {proc_desc}       Procedure description
  {modality}        Modality  (CT, MR, DX, XA, ...)
  {study_uid}       Study Instance UID  (leave blank if not known)
  {sending_app}     MSH-3  Sending application
  {sending_fac}     MSH-4  Sending facility
  {recv_app}        MSH-5  Receiving application
  {recv_fac}        MSH-6  Receiving facility
  {assigning_auth}  PID-3 assigning authority  (e.g. HOSP)

Any {placeholder} not recognised is left as-is so you can see what still
needs filling in.

EXAMPLE - adding your own template
-----------------------------------
Create a new file, e.g.:  MyCustomMessage.hl7

  # name: ZXX^Z01 - My Custom Message
  # description: Internal workflow notification for our RIS integration.
  MSH|^~\&|{sending_app}|{sending_fac}|RIS|HOSP|{ts}||ZXX^Z01|{msgid}|P|2.3
  PID|1||{pid}^^^HOSP^MR||{name}||{dob}|{sex}
  ZXX|{acc}|CUSTOM_FIELD|{proc_desc}

Save the file, restart the tool (or click Refresh Templates), and it will
appear in the dropdown.
