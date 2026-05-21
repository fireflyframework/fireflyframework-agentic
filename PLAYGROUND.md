# MCP with Firefly

## Setup
```
claude mcp remove firefly
claude mcp list
```

```
MCP_STATIC_KEY=_O4S3ftI9trHhWEOwfudqsMVzYsKx5x7DCAQT2z6Moo
MCP_STATIC_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
claude mcp add --scope user --transport http firefly  https://firefly-mcp.mangosmoke-5d24814d.spaincentral.azurecontainerapps.io/mcp/  --header "Authorization: Bearer $MCP_STATIC_KEY"
claude mcp list
```


## Execution
Once inside: `claude`

Using firefly, list the corpora

Using firefly, knowledge_search on synthetic_unstructured01 for 'GDPR rights'

