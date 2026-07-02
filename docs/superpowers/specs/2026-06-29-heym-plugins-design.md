# Heym Plugins — Tasarım Dokümanı

**Tarih:** 2026-06-29
**Durum:** Onaylandı (brainstorming) → implementation plan bekliyor
**Kapsam:** heymrun'a plugin (zip ile kurulabilen custom node) desteği

## 1. Amaç

Heym'e, kurulu instance'a `.zip` olarak yüklenen **plugin** desteği eklemek. Bir
plugin, canvas'ta bir **custom node** gibi davranır; **action** (3rd-party API
çağrısı dahil) veya **trigger** tipinde olabilir. Bu özellik, enterprise
müşterilere on-demand plugin yazılacak ticari genişleme yüzeyidir.

Gereksinimler:
- Global `plugins enabled` env flag'i (varsayılan kapalı).
- Pluginler zip olarak kurulabilir / kaldırılabilir.
- Plugin = custom node (trigger / action / herhangi bir 3rd-party).
- Install / uninstall yalnızca **admin** (kuruluma yetkili kişi) tarafından.
- UI: Ayarlar dialog'unda **Plugins** sekmesi.
- Plugin dokümanları `/documentation` altında listelenir.
- Kurulu pluginler `workflow_dsl_prompt.py` üzerinden AI prompt'a enjekte edilir,
  böylece AI assistant ve chat canvas plugin node'larını üretebilir.

## 2. Temel Kararlar (brainstorming çıktısı)

| Karar | Sonuç |
|-------|-------|
| Çalıştırma modeli | Pluginler **Heym tarafından iletilen, admin'in kurduğu güvenilir kod**. Handler **backend process'i içinde dinamik import** ile, yerleşik bir node gibi tam yetkiyle çalışır (ağ açık, tüm kütüphaneler serbest). Kısıtlı tool-sandbox kullanılmaz. |
| Bağımlılıklar | Plugin manifest'i `dependencies` (pip paketleri) bildirebilir; kurulum sırasında o Heym instance'ına `uv pip install` ile kurulur. |
| Node entegrasyonu | **A Yaklaşımı**: tek `plugin` + `pluginTrigger` statik node tipi, `pluginId` ile parametrize. Per-plugin dinamik NodeType yok. |
| Admin gate | Yeni, plugin'e özel env allowlist: `HEYM_PLUGIN_ADMIN_EMAILS` (kuruluma yetkili maillerin listesi). |
| Enable flag | `HEYM_PLUGINS_ENABLED` env, varsayılan kapalı; tüm alt sistemi (API + UI + DSL enjeksiyonu) gate'ler. |
| Kapsam | Hem `action`/3rd-party hem `trigger` plugin tipleri. Trigger için özel polling/scheduler altyapısı **kurulmaz**; trigger node'u workflow çalıştığında/elle tetiklendiğinde çalışır. |
| Config UI | Manifest `fields`'tan üretilen **şema-tabanlı** form. Per-plugin Vue bileşeni yok. |

## 3. Plugin Paketi (zip) Formatı

```
my-plugin.zip
├── plugin.json      # manifest
├── handler.py       # action: def run(inputs, config, ctx) -> dict
│                    # trigger: def trigger(config, ctx) -> dict
├── README.md        # /documentation altında render edilecek doküman
└── icon.svg         # opsiyonel, palet ikonu
```

### 3.1 `plugin.json` Manifest

```json
{
  "id": "acme-crm",
  "name": "Acme CRM",
  "version": "1.0.0",
  "kind": "action",
  "description": "Acme CRM'e kayıt gönderir/çeker",
  "entry": "handler.py",
  "dependencies": ["requests==2.32.3"],
  "fields": [
    { "key": "apiKey", "label": "API Key", "type": "string", "secret": true, "required": true },
    { "key": "recordId", "label": "Record ID", "type": "string", "dynamic": true, "expression": true }
  ],
  "dslHint": "Acme CRM kaydı oluşturmak/çekmek için bu node'u kullan.",
  "docSlug": "acme-crm"
}
```

Manifest alanları (Pydantic `PluginManifest` ile doğrulanır):
- `id` — `^[a-z0-9-]+$`, instance içinde unique. Tekrar yükleme = sürüm güncelleme.
- `name`, `version`, `description`.
- `kind` — `"action"` | `"trigger"`.
- `entry` — Python handler dosyası (varsayılan `handler.py`).
- `dependencies` — opsiyonel pip paketleri listesi; kurulumda `uv pip install` ile instance'a kurulur.
- `fields[]` — config alanları. Her alan: `key`, `label`, `type`
  (`string`|`number`|`boolean`|`select`), opsiyonel `required`, `secret`,
  `default`, `options` (select için), `dynamic` (runtime/expression
  eligible), `expression` (expression dialog'a açık).
- `dslHint` — AI prompt'a eklenecek kısa kullanım ipucu.
- `docSlug` — `/documentation` altındaki doküman slug'ı.

`fields` üç yeri besler (AGENTS.md node-integration kuralı):
1. Canvas config formu.
2. Expression dialog metadata'sı (`dynamic`/`expression` alanlar için 1/n
   navigasyon + dinamik doldurma).
3. AI autofill (agent ikonu eligibility).

### 3.2 Handler Sözleşmesi

- **action**: `def run(inputs: dict, config: dict, ctx: dict) -> dict`
- **trigger**: `def trigger(config: dict, ctx: dict) -> dict`

`ctx` serileştirilebilir bağlam bilgilerini taşır (executor objesi değil).
Handler **backend process'i içinde**, diskten dinamik import edilen modül olarak
çalışır (yerleşik node gibi tam yetki: ağ + tüm kütüphaneler). Pluginler
güvenilir (Heym-iletili, admin-kurulu) olduğu için kısıtlı sandbox uygulanmaz.

## 4. Backend

### 4.1 Veri Modeli — `plugins` tablosu (Alembic migration)

| Kolon | Tip | Not |
|-------|-----|-----|
| `id` | UUID PK | |
| `plugin_id` | str, unique, index | manifest `id` |
| `name` | str | |
| `version` | str | |
| `kind` | str | `action` \| `trigger` |
| `description` | text | |
| `manifest` | JSONB | tüm `plugin.json` |
| `enabled` | bool, default true | |
| `installed_by` | str | admin email |
| `created_at` / `updated_at` | timestamptz | |

Plugin dosyaları diskte `HEYM_PLUGINS_DIR/<plugin_id>/` altında; DB yalnızca
metadata + manifest tutar.

### 4.2 Config (`backend/app/config.py`)

- `plugins_enabled: bool = False` → `HEYM_PLUGINS_ENABLED`
- `plugin_admin_emails: str = ""` → `HEYM_PLUGIN_ADMIN_EMAILS` (virgülle ayrılmış)
- `plugins_dir: str = "data/plugins"` → `HEYM_PLUGINS_DIR`

`.env.example`, `docker-compose.yml` ve `deploy.sh`/`run.sh` örneklerine eklenir
(mevcut `DOCKER_LOGS_*` deseniyle aynı şekilde).

### 4.3 API (`backend/app/api/plugins.py`)

`logs.py`'deki gate desenini izler:
- `require_plugins_enabled()` — flag kapalıysa 404.
- `require_plugin_admin(current_user)` — email `HEYM_PLUGIN_ADMIN_EMAILS`'te
  değilse 403.

Endpointler (hepsi `plugins_enabled` arkasında):
- `GET /api/plugins` — kurulu plugin listesi (giriş yapan herkes; palet + docs
  için). Manifest + `README.md` markdown'ı döner.
- `POST /api/plugins/install` — **admin** — multipart zip upload.
- `DELETE /api/plugins/{plugin_id}` — **admin** — DB kaydı + disk klasörü sil.
- `PATCH /api/plugins/{plugin_id}` — **admin** — `enabled` toggle.

### 4.4 Install Doğrulaması

- Zip boyut limiti.
- Path-traversal / zip-slip koruması (üye yolları hedef dizin altında kalmalı).
- `plugin.json` Pydantic şema validasyonu; `id` format kontrolü.
- Aynı `plugin_id` tekrar yüklenirse sürüm güncellenir (upsert).
- `dependencies` varsa `uv pip install <paketler>` çalıştırılır; başarısızsa
  install fail eder ve kısmi kurulum geri alınır (disk klasörü silinir).

### 4.5 Çalıştırma Seam'i (A Yaklaşımı)

- `node_execution/registry.py`'ye iki kayıt:
  `"plugin": "plugin_node"`, `"pluginTrigger": "plugin_trigger_node"`.
- `node_execution/nodes/plugin_node.py` (tek dispatcher):
  1. `node_data.pluginId`'den manifesti diskten bul (yoksa/disabled ise hata).
  2. `config` alanlarını expression resolve et (`ctx.executor.resolve_expression`).
  3. `HEYM_PLUGINS_DIR/<pluginId>/handler.py`'yi dinamik import et (modül cache'li).
  4. `run(inputs, config, ctx_safe)` çağır, dönen dict'i çıktı olarak ver.
- `node_execution/nodes/plugin_trigger_node.py` → `trigger(config, ctx_safe)`
  çağırır; çıktıyı entry/trigger node çıktısı olarak verir.
- Retry, tracing, cancellation, final `NodeResult` paketleme `WorkflowExecutor`'da
  kalır (AGENTS.md WorkflowExecutor modülerlik kuralı). `WorkflowExecutor`'a yeni
  `node_type` branch'i eklenmez.

## 5. Frontend

### 5.1 Tipler & Palet

- `frontend/src/types/workflow.ts` `NodeType` union'a `"plugin"` ve
  `"pluginTrigger"` eklenir. Node `data`: `{ pluginId: string, config: Record<string, unknown> }`.
- `NodePanel`: kurulu pluginler `GET /api/plugins`'ten çekilir; her plugin kendi
  adı/ikonuyla ayrı kart olarak görünür ama bırakıldığında `type` +
  `pluginId` ile node yaratır. `plugins_enabled` kapalıysa bölüm görünmez.

### 5.2 Config Formu

- `components/Panels/propertiesPanel/nodes/PluginNodeProperties.vue` (tek bileşen):
  manifest `fields`'tan şema-tabanlı form üretir
  (string/number/boolean/select/secret). `expression`/`dynamic` bayraklı alanlar
  expression dialog metadata'sına ve AI autofill'e açılır.
- `PropertiesPanel.vue` ince kabuk kalır; `selectedNode.type` branch'i eklenmez
  (AGENTS.md PropertiesPanel modülerlik kuralı).

### 5.3 Ayarlar → Plugins Sekmesi

- `components/Layout/UserSettingsDialog.vue` `SettingsTab` tipine `"plugins"`
  eklenir.
- Sekme: kurulu plugin listesi + enable/disable toggle. Zip upload ve uninstall
  butonları yalnızca admin (`HEYM_PLUGIN_ADMIN_EMAILS`) için görünür; backend
  ayrıca zorunlu kılar. `plugins_enabled` kapalıysa sekme hiç görünmez.

## 6. /documentation Entegrasyonu

- `GET /api/plugins` her plugin için manifest + `README.md` markdown'ı döner.
- `DocsView`, statik `DOCS_MANIFEST`'e ek olarak runtime'da dinamik bir
  **"Plugins"** kategorisi gösterir: kurulu pluginler `/documentation` altında
  listelenir, markdown plugin `README.md`'sinden render edilir. Statik
  `manifest.ts`'e dokunulmaz.

## 7. DSL Prompt Enjeksiyonu

- `workflow_dsl_prompt.py` içindeki `build_assistant_prompt(...)` fonksiyonuna,
  kurulu **ve** enabled pluginler için dinamik bir **"Installed Plugins"** bölümü
  eklenir: her plugin'in `id`, `kind`, `description`, `fields`, `dslHint`
  bilgisi.
- Statik `WORKFLOW_DSL_SYSTEM_PROMPT` sabitine **dokunulmaz** → heymweb DSL sync
  guard testi (sync diff = 0) yeşil kalır.
- Böylece AI assistant ve chat canvas plugin node'larını üretebilir.

## 8. Güvenlik / Güven Modeli

- **Güven modeli:** Pluginler Heym tarafından iletilir ve yalnızca admin kurar.
  Bu yüzden plugin kodu **güvenilir** kabul edilir ve yerleşik node'lar gibi
  backend process içinde tam yetkiyle çalışır (ağ + tüm kütüphaneler). Bu
  bilinçli bir karar (enterprise on-demand plugin yüzeyi).
- Asıl güvenlik sınırı **kurulum kapısı**: install/uninstall/dependency-install
  hem `HEYM_PLUGINS_ENABLED` hem `HEYM_PLUGIN_ADMIN_EMAILS` ile gate'li.
- Zip-slip / boyut / şema doğrulaması.
- `dependencies` pip kurulumu yalnızca admin install akışında tetiklenir.
- `secret` işaretli alanlar UI'da maskelenir ve loglara yazılmaz.
- Handler'a executor objesi değil, serileştirilmiş `ctx` verilir.

## 9. Test Planı

**Backend (zorunlu):**
- Manifest validasyonu (geçerli + geçersiz `id`/`kind`/`fields`).
- Zip-slip / boyut limiti reddi.
- Admin gate: yetkisiz email → 403.
- Flag-off: `HEYM_PLUGINS_ENABLED=false` → 404.
- Install → list → uninstall akışı (disk + DB).
- `enabled` toggle (`PATCH`).
- Dependency install adımı (mock'lu `uv pip install`); başarısızlıkta rollback.
- `plugin_node` / `plugin_trigger_node` dispatcher: diskten örnek bir
  `handler.py` dinamik import edilir, `run` / `trigger` davranışı + expression
  resolve doğrulanır.
- DSL prompt enjeksiyonu: `build_assistant_prompt` çıktısında plugin bölümü;
  statik `WORKFLOW_DSL_SYSTEM_PROMPT` değişmediğini doğrulayan sync guard.

**Frontend:**
- lint + typecheck.
- Pratikse bir Playwright akışı (admin için Plugins sekmesi + node paleti
  görünürlüğü; flag/role'a göre gizlenme).

## 10. Dokümantasyon

- Yeni node tipleri (`plugin`, `pluginTrigger`) için `heym-documentation` skill
  ile node referans dokümanları güncellenir: `frontend/src/docs/content/nodes/`,
  `manifest.ts`, `reference/features.md`, `node-types.md`. Plugin altyapısı için
  kısa bir kavramsal sayfa (kurulum, manifest formatı, güvenlik).

## 11. Kapsam Dışı (sonraki iterasyon)

- Trigger pluginleri için arka plan polling/scheduler/webhook dispatch altyapısı.
- Plugin marketplace / uzaktan repo'dan kurulum.
- Per-plugin özel Vue bileşenleri (B Yaklaşımı).
- Plugin sürüm geçmişi / rollback.
