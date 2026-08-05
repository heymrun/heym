<script setup lang="ts">
import { computed } from "vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  converterExpressionFieldCount,
  converterExpressionFieldIndex,
  converterTargetFormatOptions,
  setConverterExpressionInputRef,
  handleConverterExpressionFieldNavigate,
  onConverterRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();

const conversionOptions = [
  { value: "csvToJson", label: "CSV → JSON" },
  { value: "jsonToCsv", label: "JSON → CSV" },
  { value: "imageToText", label: "Image → Text (OCR)" },
  { value: "pdfToText", label: "PDF → Text (OCR)" },
  { value: "fileConvert", label: "File → Another format" },
];

// Tesseract codes. "auto" runs script detection first and picks the matching model.
const languageOptions = [
  { value: "auto", label: "Auto detect" },
  { value: "eng", label: "English (eng)" },
  { value: "tur", label: "Turkish (tur)" },
  { value: "deu", label: "German (deu)" },
  { value: "fra", label: "French (fra)" },
  { value: "spa", label: "Spanish (spa)" },
  { value: "ita", label: "Italian (ita)" },
  { value: "por", label: "Portuguese (por)" },
  { value: "nld", label: "Dutch (nld)" },
  { value: "rus", label: "Russian (rus)" },
  { value: "ara", label: "Arabic (ara)" },
  { value: "chi_sim", label: "Chinese Simplified (chi_sim)" },
  { value: "jpn", label: "Japanese (jpn)" },
  { value: "kor", label: "Korean (kor)" },
  { value: "custom", label: "Custom codes…" },
];

const encodingOptions = [
  { value: "utf-8", label: "UTF-8 (recommended)" },
  { value: "utf-8-sig", label: "UTF-8 with BOM" },
  { value: "utf-16", label: "UTF-16" },
  { value: "latin-1", label: "Latin-1 (ISO-8859-1)" },
  { value: "cp1252", label: "Windows-1252" },
  { value: "cp1254", label: "Windows-1254 (Turkish)" },
  { value: "iso-8859-9", label: "ISO-8859-9 (Turkish)" },
  { value: "ascii", label: "ASCII" },
];

const psmOptions = [
  { value: "3", label: "3 — Automatic page (default)" },
  { value: "1", label: "1 — Automatic with orientation detection" },
  { value: "4", label: "4 — Single column of variable-size text" },
  { value: "6", label: "6 — Single uniform block" },
  { value: "7", label: "7 — Single line" },
  { value: "11", label: "11 — Sparse text" },
  { value: "12", label: "12 — Sparse text with orientation detection" },
  { value: "13", label: "13 — Raw line" },
];

const conversion = computed((): string => selectedNode.value?.data.conversion || "csvToJson");
const isOcr = computed(
  (): boolean => conversion.value === "imageToText" || conversion.value === "pdfToText",
);
const isFileConvert = computed((): boolean => conversion.value === "fileConvert");
const usesFile = computed((): boolean => isOcr.value || isFileConvert.value);
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="converter-conversion-field"
    >
      <Label>Conversion</Label>
      <Select
        :model-value="conversion"
        :options="conversionOptions"
        @update:model-value="updateNodeData('conversion', $event || 'csvToJson')"
      />
      <p class="text-xs text-muted-foreground">
        Choose the direction of the conversion.
      </p>
    </div>

    <div
      v-if="!usesFile"
      class="space-y-2"
      data-testid="converter-source-field"
    >
      <Label>Source</Label>
      <ExpressionInput
        :ref="(el: unknown) => setConverterExpressionInputRef('source', el)"
        :model-value="selectedNode.data.source || ''"
        placeholder="$input.text"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Source"
        field-key="source"
        :navigation-enabled="converterExpressionFieldCount > 1"
        :navigation-index="converterExpressionFieldIndex('source')"
        :navigation-total="converterExpressionFieldCount"
        @navigate="handleConverterExpressionFieldNavigate"
        @register-field-index="onConverterRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('source', $event)"
      />
      <p class="text-xs text-muted-foreground">
        The data to convert. Leave empty to use this node's first input.
      </p>
    </div>

    <div
      v-if="usesFile"
      class="space-y-2"
      data-testid="converter-ocr-file-field"
    >
      <Label>File</Label>
      <ExpressionInput
        :ref="(el: unknown) => setConverterExpressionInputRef('converterFileId', el)"
        :model-value="selectedNode.data.converterFileId || ''"
        placeholder="$Upload.file.id"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="File"
        field-key="converterFileId"
        :navigation-enabled="converterExpressionFieldCount > 1"
        :navigation-index="converterExpressionFieldIndex('converterFileId')"
        :navigation-total="converterExpressionFieldCount"
        @navigate="handleConverterExpressionFieldNavigate"
        @register-field-index="onConverterRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('converterFileId', $event)"
      />
      <p class="text-xs text-muted-foreground">
        A Heym Drive file id, file object, or download URL. Upload it with a File upload
        trigger, fetch it with a Drive node, or take one from an agent's generated files.
        Leave empty to use this node's first input.
      </p>
    </div>

    <div
      v-if="!usesFile"
      class="space-y-2"
      data-testid="converter-delimiter-field"
    >
      <Label>Delimiter</Label>
      <Input
        :model-value="selectedNode.data.delimiter || ','"
        placeholder=","
        @update:model-value="updateNodeData('delimiter', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Single-character field separator (default <code>,</code>).
      </p>
    </div>

    <div
      v-if="conversion === 'csvToJson'"
      class="space-y-2"
      data-testid="converter-has-header-field"
    >
      <div class="flex items-center gap-2">
        <input
          id="converter-has-header"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="selectedNode.data.hasHeader !== false"
          @change="updateNodeData('hasHeader', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="converter-has-header"
          class="text-sm font-medium"
        >
          First row is a header
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        When enabled, header values become the keys of each row object.
      </p>
    </div>

    <div
      v-if="conversion === 'csvToJson'"
      class="space-y-2"
      data-testid="converter-trim-values-field"
    >
      <div class="flex items-center gap-2">
        <input
          id="converter-trim-values"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="selectedNode.data.trimValues !== false"
          @change="updateNodeData('trimValues', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="converter-trim-values"
          class="text-sm font-medium"
        >
          Trim whitespace
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        Strip surrounding spaces from header names and cell values.
      </p>
    </div>

    <template v-if="conversion === 'jsonToCsv'">
      <div
        class="space-y-2"
        data-testid="converter-include-header-field"
      >
        <div class="flex items-center gap-2">
          <input
            id="converter-include-header"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.includeHeader !== false"
            @change="updateNodeData('includeHeader', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="converter-include-header"
            class="text-sm font-medium"
          >
            Include header row
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Write a header row derived from the object keys.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="converter-columns-field"
      >
        <Label>Columns (optional)</Label>
        <Input
          :model-value="selectedNode.data.converterColumns || ''"
          placeholder="name, age, email"
          @update:model-value="updateNodeData('converterColumns', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Comma-separated column order. Leave empty to infer from the data.
        </p>
      </div>
    </template>

    <div
      v-if="isFileConvert"
      class="space-y-2"
      data-testid="converter-target-format-field"
    >
      <Label>Target format</Label>
      <Select
        :model-value="selectedNode.data.converterTargetFormat || ''"
        :options="converterTargetFormatOptions"
        @update:model-value="updateNodeData('converterTargetFormat', $event || '')"
      />
      <p class="text-xs text-muted-foreground">
        Documents convert to pdf, docx, html, md, txt, or epub, and csv output needs a JSON
        array of objects. Images convert between jpg, png, bmp, and webp. An image cannot
        become a document, so use Image to Text to read one instead.
      </p>
    </div>

    <template v-if="isOcr">
      <div
        class="space-y-2"
        data-testid="converter-ocr-language-field"
      >
        <Label>Language</Label>
        <Select
          :model-value="selectedNode.data.ocrLanguage || 'auto'"
          :options="languageOptions"
          @update:model-value="updateNodeData('ocrLanguage', $event || 'auto')"
        />
        <p class="text-xs text-muted-foreground">
          Auto detect reads the script from the page and picks the matching Tesseract model.
          Naming the language is more accurate when you know it.
        </p>
      </div>

      <div
        v-if="selectedNode.data.ocrLanguage === 'custom'"
        class="space-y-2"
        data-testid="converter-ocr-language-custom-field"
      >
        <Label>Custom language codes</Label>
        <Input
          :model-value="selectedNode.data.ocrLanguageCustom || ''"
          placeholder="eng+tur"
          @update:model-value="updateNodeData('ocrLanguageCustom', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Tesseract codes joined with <code>+</code>. The language data has to be installed on
          the backend.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="converter-ocr-encoding-field"
      >
        <Label>Text encoding</Label>
        <Select
          :model-value="selectedNode.data.ocrEncoding || 'utf-8'"
          :options="encodingOptions"
          @update:model-value="updateNodeData('ocrEncoding', $event || 'utf-8')"
        />
        <p class="text-xs text-muted-foreground">
          UTF-8 keeps every recognized character. A narrower charset replaces what it cannot
          represent, so pick one only when a downstream system needs it.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="converter-ocr-normalize-field"
      >
        <div class="flex items-center gap-2">
          <input
            id="converter-ocr-normalize"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.ocrNormalizeUnicode !== false"
            @change="
              updateNodeData('ocrNormalizeUnicode', ($event.target as HTMLInputElement).checked)
            "
          >
          <Label
            for="converter-ocr-normalize"
            class="text-sm font-medium"
          >
            Normalize Unicode (NFC)
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Combines separate accent marks into single characters, so <code>s</code> plus a cedilla
          becomes <code>ş</code>.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="converter-ocr-psm-field"
      >
        <Label>Page segmentation</Label>
        <Select
          :model-value="selectedNode.data.ocrPsm || '3'"
          :options="psmOptions"
          @update:model-value="updateNodeData('ocrPsm', $event || '3')"
        />
        <p class="text-xs text-muted-foreground">
          How Tesseract splits the page. Single line or single block helps on receipts, labels,
          and cropped screenshots.
        </p>
      </div>

      <div
        v-if="conversion === 'pdfToText'"
        class="space-y-2"
        data-testid="converter-ocr-dpi-field"
      >
        <Label>Rasterization DPI</Label>
        <Input
          :model-value="String(selectedNode.data.ocrDpi ?? 300)"
          type="number"
          placeholder="300"
          @update:model-value="updateNodeData('ocrDpi', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Pages are rendered to images before OCR. 300 suits most documents; raise it for small
          print, lower it for speed.
        </p>
      </div>

      <div
        v-if="conversion === 'pdfToText'"
        class="space-y-2"
        data-testid="converter-ocr-page-range-field"
      >
        <Label>Page range (optional)</Label>
        <ExpressionInput
          :ref="(el: unknown) => setConverterExpressionInputRef('ocrPageRange', el)"
          :model-value="selectedNode.data.ocrPageRange || ''"
          placeholder="2-5"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Page range"
          field-key="ocrPageRange"
          :navigation-enabled="converterExpressionFieldCount > 1"
          :navigation-index="converterExpressionFieldIndex('ocrPageRange')"
          :navigation-total="converterExpressionFieldCount"
          @navigate="handleConverterExpressionFieldNavigate"
          @register-field-index="onConverterRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('ocrPageRange', $event)"
        />
        <p class="text-xs text-muted-foreground">
          <code>3</code> for one page or <code>2-5</code> for a span. Empty means every page.
          Every page goes through OCR, so long documents take a while.
        </p>
      </div>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <p class="text-xs text-muted-foreground">
        The converted value is available as <code>${{ selectedNode.data.label || 'converter' }}.result</code>.
      </p>
      <p
        v-if="isOcr"
        class="text-xs text-muted-foreground"
      >
        OCR runs also expose <code>.language</code>, <code>.encoding</code>,
        <code>.page_count</code>, <code>.pages</code>, and <code>.file</code>.
      </p>
      <p
        v-if="isFileConvert"
        class="text-xs text-muted-foreground"
      >
        The converted file is stored as a new Drive file and exposed as <code>.id</code>,
        <code>.filename</code>, <code>.mime_type</code>, <code>.size_bytes</code>, and
        <code>.download_url</code>. The original file is left untouched.
      </p>
    </div>
  </template>
</template>
