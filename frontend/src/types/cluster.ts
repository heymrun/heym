export interface ClusterInstance {
  id: string;
  name: string;
  role: string;
  enabled: boolean;
  weight: number;
  weight_configured: boolean;
  version: string;
  docker_ok: boolean;
  db_latency_ms: number;
  live: boolean;
  compatible: boolean;
  heartbeat_at: string | null;
}

export interface ClusterPlacementRatio {
  mainOnlyPercent: number;
  anywherePercent: number;
}

export interface ClusterSettings {
  cluster_enabled: boolean;
  automatic_weighting: boolean;
  instances: ClusterInstance[];
  placement_ratio: ClusterPlacementRatio;
}

export interface ClusterInstanceUpdate {
  name: string;
  enabled: boolean;
  weight: number;
}
