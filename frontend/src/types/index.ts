export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  subscription: Subscription;
  settings: UserSettings;
  created_at: string;
  last_login_at?: string;
}

export interface Subscription {
  plan: "free" | "starter" | "growth" | "professional" | "agency";
  stripe_customer_id?: string;
  stripe_subscription_id?: string;
  status: "active" | "past_due" | "canceled" | "trialing";
  trial_ends_at?: string;
  current_period_end?: string;
  minutes_included: number;
  minutes_used: number;
}

export interface UserSettings {
  timezone: string;
  notifications_email: boolean;
  notifications_sms: boolean;
}

export interface Company {
  id: string;
  user_id: string;
  name: string;
  industry?: string;
  website?: string;
  phone_numbers: PhoneNumber[];
  integrations: Integrations;
  branding: Branding;
  business_hours: BusinessHours;
  created_at: string;
  updated_at: string;
}

export interface PhoneNumber {
  id: string;
  number: string;
  twilio_sid: string;
  friendly_name: string;
  agent_id?: string;
  type: "local" | "toll_free";
  status: "active" | "released";
}

export interface Integrations {
  google?: IntegrationConfig;
  microsoft?: IntegrationConfig;
}

export interface IntegrationConfig {
  connected: boolean;
  email?: string;
  calendar_id?: string;
  scopes?: string[];
}

export interface Branding {
  logo_url?: string;
  primary_color?: string;
  company_greeting?: string;
}

export interface BusinessHours {
  timezone: string;
  schedule: Schedule[];
  holidays: string[];
}

export interface Schedule {
  day: number;
  enabled: boolean;
  open: string;
  close: string;
}

export interface Agent {
  id: string;
  company_id: string;
  user_id: string;
  name: string;
  type: "receptionist" | "scheduler" | "reminder" | "qualifier";
  status: "active" | "paused" | "draft";
  voice: Voice;
  persona: Persona;
  capabilities: Capabilities;
  calendar_settings?: CalendarSettings;
  transfer_settings?: TransferSettings;
  conversation_settings?: ConversationSettings;
  knowledge_base: KnowledgeItem[];
  analytics: AgentAnalytics;
  created_at: string;
  updated_at: string;
}

export interface Voice {
  voice_id: string;
  name: string;
  speed: number;
  pitch: number;
  stability: number;
  style: number;
}

export interface Persona {
  display_name: string;
  role: string;
  personality: string[];
  greeting: string;
  system_prompt?: string;
}

export interface Capabilities {
  answer_calls: boolean;
  make_calls: boolean;
  schedule_appointments: boolean;
  send_confirmations: boolean;
  take_messages: boolean;
  transfer_calls: boolean;
  qualify_leads: boolean;
}

export interface CalendarSettings {
  enabled: boolean;
  calendar_id?: string;
  slot_duration_minutes: number;
  buffer_minutes: number;
  max_advance_days: number;
  services: Service[];
}

export interface Service {
  name: string;
  duration_minutes: number;
  description: string;
}

export interface TransferSettings {
  enabled: boolean;
  default_number?: string;
  rules: TransferRule[];
}

export interface ConversationSettings {
  max_duration_seconds: number;
  interruption_handling: string;
  end_phrase: string;
  silence_timeout_seconds: number;
  language: string;
}

export interface TransferRule {
  condition: string;
  destination: string;
  announce: boolean;
}

export interface KnowledgeItem {
  id: string;
  type: "faq" | "document" | "website";
  title: string;
  content: string;
  source_url?: string;
  created_at: string;
}

export interface AgentAnalytics {
  total_calls: number;
  total_minutes: number;
  avg_duration_seconds: number;
  appointments_booked: number;
  messages_taken: number;
  transfers_made: number;
  satisfaction_avg: number;
}

export interface Call {
  id: string;
  agent_id: string;
  company_id: string;
  user_id: string;
  twilio_call_sid: string;
  direction: "inbound" | "outbound";
  from_number: string;
  to_number: string;
  status: "queued" | "ringing" | "in_progress" | "completed" | "busy" | "no_answer" | "failed";
  initiated_at: string;
  answered_at?: string;
  ended_at?: string;
  duration_seconds?: number;
  caller?: CallerInfo;
  transcript: TranscriptMessage[];
  summary?: string;
  outcome?: CallOutcome;
  sentiment_analysis?: SentimentAnalysis;
  actions: CallAction[];
  appointment?: AppointmentInfo;
  message?: MessageInfo;
  lead?: LeadInfo;
  recording_url?: string;
  recording_duration?: number;
  billable_minutes: number;
  cost_cents: number;
  tags: string[];
  internal_notes?: string;
  created_at: string;
  updated_at: string;
}

export interface CallerInfo {
  name?: string;
  phone: string;
  email?: string;
  company?: string;
}

export interface TranscriptMessage {
  id: string;
  speaker: "agent" | "caller";
  text: string;
  timestamp: string;
  confidence: number;
  sentiment: number;
}

export type CallOutcome =
  | "appointment_scheduled"
  | "message_taken"
  | "transferred"
  | "information_provided"
  | "lead_qualified"
  | "callback_requested"
  | "dropped"
  | "voicemail";

export interface SentimentAnalysis {
  overall_score: number;
  trend: number[];
  keywords: string[];
  escalation_needed: boolean;
}

export interface CallAction {
  type: string;
  timestamp: string;
  details: Record<string, unknown>;
  success: boolean;
  error?: string;
}

export interface AppointmentInfo {
  calendar_event_id: string;
  title: string;
  start_time: string;
  end_time: string;
  attendee_email: string;
}

export interface MessageInfo {
  content: string;
  urgency: "low" | "normal" | "high" | "urgent";
  delivered: boolean;
  delivered_at?: string;
}

export interface LeadInfo {
  score: number;
  qualified: boolean;
  fields: Record<string, unknown>;
  notes: string;
}

export interface UsageStats {
  current_period_start: string;
  current_period_end: string;
  minutes_used: number;
  minutes_included: number;
  overage_minutes: number;
  estimated_overage_cost: number;
  calls_count: number;
}

export interface Invoice {
  id: string;
  stripe_invoice_id: string;
  amount_cents: number;
  currency: string;
  status: string;
  period_start: string;
  period_end: string;
  hosted_invoice_url?: string;
  invoice_pdf?: string;
  created_at: string;
}

export interface Plan {
  id: string;
  name: string;
  price_monthly: number;
  minutes_included: number;
  max_agents: number | "unlimited";
  features: string[];
}
