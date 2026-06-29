<script setup lang="ts">
import TextInputNodeProperties from "./TextInputNodeProperties.vue";
import CronNodeProperties from "./CronNodeProperties.vue";
import FileUploadTriggerNodeProperties from "./FileUploadTriggerNodeProperties.vue";
import TelegramTriggerNodeProperties from "./TelegramTriggerNodeProperties.vue";
import SlackTriggerNodeProperties from "./SlackTriggerNodeProperties.vue";
import DiscordTriggerNodeProperties from "./DiscordTriggerNodeProperties.vue";
import ImapTriggerNodeProperties from "./ImapTriggerNodeProperties.vue";
import WebsocketTriggerNodeProperties from "./WebsocketTriggerNodeProperties.vue";
import LlmNodeProperties from "./LlmNodeProperties.vue";
import AgentNodeProperties from "./AgentNodeProperties.vue";
import ConditionNodeProperties from "./ConditionNodeProperties.vue";
import SwitchNodeProperties from "./SwitchNodeProperties.vue";
import ExecuteNodeProperties from "./ExecuteNodeProperties.vue";
import HttpNodeProperties from "./HttpNodeProperties.vue";
import WebsocketSendNodeProperties from "./WebsocketSendNodeProperties.vue";
import OutputNodeProperties from "./OutputNodeProperties.vue";
import ConsoleLogNodeProperties from "./ConsoleLogNodeProperties.vue";
import ChartOutputNodeProperties from "./ChartOutputNodeProperties.vue";
import SlackNodeProperties from "./SlackNodeProperties.vue";
import DiscordNodeProperties from "./DiscordNodeProperties.vue";
import TelegramNodeProperties from "./TelegramNodeProperties.vue";
import SendEmailNodeProperties from "./SendEmailNodeProperties.vue";
import ErrorHandlerNodeProperties from "./ErrorHandlerNodeProperties.vue";
import MergeNodeProperties from "./MergeNodeProperties.vue";
import SetJsonOutputMapperNodeProperties from "./SetJsonOutputMapperNodeProperties.vue";
import WaitNodeProperties from "./WaitNodeProperties.vue";
import VariableNodeProperties from "./VariableNodeProperties.vue";
import LoopNodeProperties from "./LoopNodeProperties.vue";
import DisableNodeNodeProperties from "./DisableNodeNodeProperties.vue";
import RedisNodeProperties from "./RedisNodeProperties.vue";
import RagNodeProperties from "./RagNodeProperties.vue";
import GristNodeProperties from "./GristNodeProperties.vue";
import LinearNodeProperties from "./LinearNodeProperties.vue";
import GithubNodeProperties from "./GithubNodeProperties.vue";
import GoogleSheetsNodeProperties from "./GoogleSheetsNodeProperties.vue";
import BigqueryNodeProperties from "./BigqueryNodeProperties.vue";
import SupabaseNodeProperties from "./SupabaseNodeProperties.vue";
import ClickhouseNodeProperties from "./ClickhouseNodeProperties.vue";
import NotionNodeProperties from "./NotionNodeProperties.vue";
import DataTableNodeProperties from "./DataTableNodeProperties.vue";
import S3NodeProperties from "./S3NodeProperties.vue";
import DriveNodeProperties from "./DriveNodeProperties.vue";
import ThrowErrorNodeProperties from "./ThrowErrorNodeProperties.vue";
import RabbitmqNodeProperties from "./RabbitmqNodeProperties.vue";
import CrawlerNodeProperties from "./CrawlerNodeProperties.vue";
import PlaywrightNodeProperties from "./PlaywrightNodeProperties.vue";
import McpCallNodeProperties from "./McpCallNodeProperties.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode } = usePropertiesPanelContext();
</script>

<template>
  <TextInputNodeProperties v-if="selectedNode?.type === 'textInput'" />
  <CronNodeProperties v-else-if="selectedNode?.type === 'cron'" />
  <FileUploadTriggerNodeProperties v-else-if="selectedNode?.type === 'fileUploadTrigger'" />
  <TelegramTriggerNodeProperties v-else-if="selectedNode?.type === 'telegramTrigger'" />
  <SlackTriggerNodeProperties v-else-if="selectedNode?.type === 'slackTrigger'" />
  <DiscordTriggerNodeProperties v-else-if="selectedNode?.type === 'discordTrigger'" />
  <ImapTriggerNodeProperties v-else-if="selectedNode?.type === 'imapTrigger'" />
  <WebsocketTriggerNodeProperties v-else-if="selectedNode?.type === 'websocketTrigger'" />
  <LlmNodeProperties v-else-if="selectedNode?.type === 'llm'" />
  <AgentNodeProperties v-else-if="selectedNode?.type === 'agent'" />
  <ConditionNodeProperties v-else-if="selectedNode?.type === 'condition'" />
  <SwitchNodeProperties v-else-if="selectedNode?.type === 'switch'" />
  <ExecuteNodeProperties v-else-if="selectedNode?.type === 'execute'" />
  <HttpNodeProperties v-else-if="selectedNode?.type === 'http'" />
  <WebsocketSendNodeProperties v-else-if="selectedNode?.type === 'websocketSend'" />
  <OutputNodeProperties v-else-if="selectedNode?.type === 'output'" />
  <ConsoleLogNodeProperties v-else-if="selectedNode?.type === 'consoleLog'" />
  <ChartOutputNodeProperties v-else-if="selectedNode?.type === 'chartOutput'" />
  <SlackNodeProperties v-else-if="selectedNode?.type === 'slack'" />
  <DiscordNodeProperties v-else-if="selectedNode?.type === 'discord'" />
  <TelegramNodeProperties v-else-if="selectedNode?.type === 'telegram'" />
  <SendEmailNodeProperties v-else-if="selectedNode?.type === 'sendEmail'" />
  <ErrorHandlerNodeProperties v-else-if="selectedNode?.type === 'errorHandler'" />
  <MergeNodeProperties v-else-if="selectedNode?.type === 'merge'" />
  <SetJsonOutputMapperNodeProperties v-else-if="selectedNode?.type === 'set' || selectedNode?.type === 'jsonOutputMapper'" />
  <WaitNodeProperties v-else-if="selectedNode?.type === 'wait'" />
  <VariableNodeProperties v-else-if="selectedNode?.type === 'variable'" />
  <LoopNodeProperties v-else-if="selectedNode?.type === 'loop'" />
  <DisableNodeNodeProperties v-else-if="selectedNode?.type === 'disableNode'" />
  <RedisNodeProperties v-else-if="selectedNode?.type === 'redis'" />
  <RagNodeProperties v-else-if="selectedNode?.type === 'rag'" />
  <GristNodeProperties v-else-if="selectedNode?.type === 'grist'" />
  <LinearNodeProperties v-else-if="selectedNode?.type === 'linear'" />
  <GithubNodeProperties v-else-if="selectedNode?.type === 'github'" />
  <GoogleSheetsNodeProperties v-else-if="selectedNode?.type === 'googleSheets'" />
  <BigqueryNodeProperties v-else-if="selectedNode?.type === 'bigquery'" />
  <SupabaseNodeProperties v-else-if="selectedNode?.type === 'supabase'" />
  <ClickhouseNodeProperties v-else-if="selectedNode?.type === 'clickhouse'" />
  <NotionNodeProperties v-else-if="selectedNode?.type === 'notion'" />
  <DataTableNodeProperties v-else-if="selectedNode?.type === 'dataTable'" />
  <S3NodeProperties v-else-if="selectedNode?.type === 's3'" />
  <DriveNodeProperties v-else-if="selectedNode?.type === 'drive'" />
  <ThrowErrorNodeProperties v-else-if="selectedNode?.type === 'throwError'" />
  <RabbitmqNodeProperties v-else-if="selectedNode?.type === 'rabbitmq'" />
  <CrawlerNodeProperties v-else-if="selectedNode?.type === 'crawler'" />
  <PlaywrightNodeProperties v-else-if="selectedNode?.type === 'playwright'" />
  <McpCallNodeProperties v-else-if="selectedNode?.type === 'mcpCall'" />
</template>
