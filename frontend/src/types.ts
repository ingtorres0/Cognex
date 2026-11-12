export type LinkStatus = "connected" | "disconnected" | "connecting";

export interface DipSwitchStatus {
  positions: string[];
  raw: string;
}

export interface TestResult {
  id: number;
  serial_number: string;
  dip_switch_status: DipSwitchStatus;
  inspection_result: boolean;
  timestamp: string;
}

export interface StatusMessage {
  type: "status";
  camera: "connected" | "disconnected";
  database: "connected" | "disconnected";
}

export interface InspectionMessage {
  type: "inspection";
  result: TestResult;
}

export type SocketMessage =
  | StatusMessage
  | InspectionMessage
  | { type: "pong" }
  | { type: "error"; message: string };
