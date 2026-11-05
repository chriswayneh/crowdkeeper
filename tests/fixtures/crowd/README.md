# Crowd response fixtures

These sanitized JSON fixtures preserve documented Crowd Data Center REST response shapes. They are
not captured from a live Crowd server. Atlassian's [JSON user response example](https://developer.atlassian.com/server/crowd/json-requests-and-responses/)
documents the user fields and nested `attributes.attributes` collection; its [REST expansion guide](https://developer.atlassian.com/server/crowd/rest/v720/)
documents attribute expansion and dot notation. The examples here combine those shapes with Crowd's
`/search`, `/user/attribute`, and `/user/group/direct` resources.

User names, email addresses, dates, URLs, group names, and attribute values are synthetic.
