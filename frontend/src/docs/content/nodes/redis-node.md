# Redis

The **Redis** node performs Redis operations: set, get, check key existence, and delete. Use it for caching, rate limiting, and key-value storage.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.value`, `$nodeLabel.success`, `$nodeLabel.exists`, `$nodeLabel.deleted` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | Redis credential from [Credentials](../tabs/credentials-tab.md) |
| `redisOperation` | `"set"` \| `"get"` \| `"hasKey"` \| `"deleteKey"` | Operation type |
| `redisKey` | expression | Redis key (supports expressions) |
| `redisValue` | expression | Value for set operation |
| `redisTtl` | number | TTL in seconds (set only, optional) |

## Operations

| Operation | Required | Output |
|-----------|----------|--------|
| `set` | key, value | `success`, `key`, `ttl` |
| `get` | key | `value`, `exists`, `key` |
| `hasKey` | key | `exists`, `key` |
| `deleteKey` | key | `deleted`, `key` |

## Example – Cache

```json
{
  "type": "redis",
  "data": {
    "label": "cacheResponse",
    "credentialId": "redis-credential-uuid",
    "redisOperation": "set",
    "redisKey": "cache:$userInput.body.userId",
    "redisValue": "$apiResponse.body",
    "redisTtl": 3600
  }
}
```

## Example – Get

```json
{
  "type": "redis",
  "data": {
    "label": "getCache",
    "credentialId": "redis-credential-uuid",
    "redisOperation": "get",
    "redisKey": "cache:$userInput.body.userId"
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Credentials Tab](../tabs/credentials-tab.md) – Add Redis credentials
- [Third-Party Integrations](../reference/integrations.md#redis) – Redis credential setup
- [Credentials Sharing](../reference/credentials-sharing.md) – Share credentials
