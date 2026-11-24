| Table Name | Number of found Foreign Key | TP | FP | FN |
|---|---:|---:|---:|---:|
| BANK | 0 | 0 | 0 | 0 |
| BANK_ACCOUNT | 0 | 0 | 0 | 2 |
| CONTACT | 0 | 0 | 0 | 6 |
| CONTACT_TYPE | 0 | 0 | 0 | 0 |
| CONTRACT | 0 | 0 | 0 | 5 |
| CURRENCY | 0 | 0 | 0 | 0 |
| DEPARTMENT | 0 | 0 | 0 | 1 |
| DOCUMENT | 3 | 3 | 0 | 8 |
| DOCUMENT_STATUS | 1 | 1 | 0 | 0 |
| DOCUMENT_TYPE | 0 | 0 | 0 | 1 |
| FINANCE_DOCUMENT | 1 | 1 | 0 | 2 |
| FORM_PROPERTY | 0 | 0 | 0 | 0 |
| INDUSTRY | 0 | 0 | 0 | 0 |
| JOB_POSITION | 0 | 0 | 0 | 0 |
| LEDGER_ACCOUNT | 0 | 0 | 0 | 1 |
| LEDGER_ACCOUNT_TYPE | 0 | 0 | 0 | 0 |
| ORGANIZATION | 1(implicit) | 0 | 0 | 0 |
| PARTNER | 1 | 1 | 0 | 7 |
| PARTNER_GROUP | 0 | 0 | 0 | 0 |
| PARTNER_TYPE | 0 | 0 | 0 | 0 |
| PERIOD | 0 | 0 | 0 | 1 |
| PERIOD_TYPE | 0 | 0 | 0 | 0 |
| PROJECT | 0 | 0 | 0 | 9 |
| PROJECT_STAGE | 0 | 0 | 0 | 2 |
| PROJECT_STAGE_GROUP | 0 | 0 | 0 | 0 |
| PROJECT_STATUS | 0 | 0 | 0 | 0 |
| PROJECT_TYPE | 0 | 0 | 0 | 0 |
| SYS_ENTITY | 0 | 0 | 0 | 1 |
| SYS_ENTITY_TYPE | 0 | 0 | 0 | 0 |
| SYS_USER | 0 | 0 | 0 | 2 |
| TAX | 0 | 0 | 0 | 0 |
| **TOTAL** | **6** | **6** | **0** | **48** |



Precision: TP / (TP + FP) = 6 / (6 + 0) = 6/67 (100%)

RECALL: TP / (TP + FN)  = 6 / (6 + 48) = 6/54 (11.11%)

Implicit key:
ORGANIZATION.ID → PARTNER.ID