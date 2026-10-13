"use client";

import { useState, useRef, useEffect, useCallback, DragEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  Loader2,
  Volume2,
  Play,
  Square,
  Phone,
  PhoneCall,
  Mic,
  Sparkles,
  FileText,
  Plus,
  Trash2,
  Upload,
  Globe,
  Webhook,
  Calendar,
  Mail,
  MessageSquare,
  Bot,
  Headphones,
  Clock,
  Users,
  Target,
  Wand2,
  Copy,
  HelpCircle,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Settings2,
  Zap,
  File,
  X,
  AlertTriangle,
  Save,
  Link,
} from "lucide-react";
import api, { apiLongRunning } from "@/lib/api";

// NVIDIA PersonaPlex Voice Options (from github.com/NVIDIA/personaplex)
const PERSONAPLEX_VOICES = [
  // Natural Female voices
  { value: "NATF0", label: "Natural Female 1", category: "Natural", gender: "female", description: "Warm, conversational American English" },
  { value: "NATF1", label: "Natural Female 2", category: "Natural", gender: "female", description: "Clear, professional tone" },
  { value: "NATF2", label: "Natural Female 3", category: "Natural", gender: "female", description: "Friendly, approachable style" },
  { value: "NATF3", label: "Natural Female 4", category: "Natural", gender: "female", description: "Calm, soothing delivery" },
  // Natural Male voices
  { value: "NATM0", label: "Natural Male 1", category: "Natural", gender: "male", description: "Confident, articulate American English" },
  { value: "NATM1", label: "Natural Male 2", category: "Natural", gender: "male", description: "Warm, trustworthy tone" },
  { value: "NATM2", label: "Natural Male 3", category: "Natural", gender: "male", description: "Energetic, engaging style" },
  { value: "NATM3", label: "Natural Male 4", category: "Natural", gender: "male", description: "Calm, measured delivery" },
  // Variety Female voices
  { value: "VARF0", label: "Variety Female 1", category: "Variety", gender: "female", description: "Dynamic, expressive style" },
  { value: "VARF1", label: "Variety Female 2", category: "Variety", gender: "female", description: "Bright, cheerful tone" },
  { value: "VARF2", label: "Variety Female 3", category: "Variety", gender: "female", description: "Sophisticated, refined delivery" },
  { value: "VARF3", label: "Variety Female 4", category: "Variety", gender: "female", description: "Gentle, reassuring style" },
  { value: "VARF4", label: "Variety Female 5", category: "Variety", gender: "female", description: "Authoritative, clear tone" },
  // Variety Male voices
  { value: "VARM0", label: "Variety Male 1", category: "Variety", gender: "male", description: "Bold, commanding presence" },
  { value: "VARM1", label: "Variety Male 2", category: "Variety", gender: "male", description: "Friendly, casual style" },
  { value: "VARM2", label: "Variety Male 3", category: "Variety", gender: "male", description: "Professional, polished delivery" },
  { value: "VARM3", label: "Variety Male 4", category: "Variety", gender: "male", description: "Deep, resonant tone" },
  { value: "VARM4", label: "Variety Male 5", category: "Variety", gender: "male", description: "Youthful, energetic style" },
];

// Agent type templates
const AGENT_TEMPLATES = [
  {
    type: "receptionist",
    name: "AI Receptionist",
    icon: Headphones,
    description: "24/7 call answering, routing, and message taking",
    color: "bg-blue-500",
    defaultPrompt: `You are {{agent_name}}, a professional virtual receptionist for {{company_name}}.

Your primary responsibilities:
- Answer incoming calls professionally and warmly
- Understand caller needs and route appropriately
- Take accurate messages when staff is unavailable
- Provide basic company information

Communication style:
- Be friendly yet professional
- Keep responses concise (1-2 sentences max)
- Always confirm you understood the caller's request
- If unsure, ask clarifying questions

Key information:
- Company: {{company_name}}
- Business hours: {{business_hours}}
- Main services: {{services}}`,
    capabilities: {
      answer_calls: true,
      make_calls: false,
      schedule_appointments: false,
      send_confirmations: false,
      take_messages: true,
      transfer_calls: true,
      qualify_leads: false,
    },
  },
  {
    type: "scheduler",
    name: "Appointment Scheduler",
    icon: Calendar,
    description: "Real-time calendar booking via voice",
    color: "bg-green-500",
    defaultPrompt: `You are {{agent_name}}, an appointment scheduling assistant for {{company_name}}.

Your primary responsibilities:
- Help callers book, reschedule, or cancel appointments
- Check real-time calendar availability
- Collect necessary booking information
- Send confirmation details

Booking process:
1. Greet the caller and ask how you can help
2. Identify the service they need
3. Check available time slots
4. Collect contact information (name, phone, email)
5. Confirm the appointment details
6. Send confirmation via email/SMS

Communication style:
- Be efficient but warm
- Clearly state available times
- Always repeat back appointment details for confirmation`,
    capabilities: {
      answer_calls: true,
      make_calls: false,
      schedule_appointments: true,
      send_confirmations: true,
      take_messages: true,
      transfer_calls: true,
      qualify_leads: false,
    },
  },
  {
    type: "reminder",
    name: "Appointment Reminder",
    icon: Clock,
    description: "Outbound reminder calls to reduce no-shows",
    color: "bg-orange-500",
    defaultPrompt: `You are {{agent_name}}, calling from {{company_name}} to remind about an upcoming appointment.

Your goal:
- Confirm the appointment is still scheduled
- Offer to reschedule if needed
- Provide any pre-appointment instructions

Call script:
1. Introduce yourself: "Hi, this is {{agent_name}} calling from {{company_name}}."
2. State purpose: "I'm calling to remind you of your appointment on {{appointment_date}} at {{appointment_time}}."
3. Confirm: "Will you be able to make it?"
4. If yes: Provide any preparation instructions
5. If no: Offer to reschedule

Keep calls brief (under 2 minutes). Be understanding if they need to reschedule.`,
    capabilities: {
      answer_calls: false,
      make_calls: true,
      schedule_appointments: false,
      send_confirmations: true,
      take_messages: false,
      transfer_calls: false,
      qualify_leads: false,
    },
  },
  {
    type: "qualifier",
    name: "Lead Qualifier",
    icon: Target,
    description: "Conversational lead capture and scoring",
    color: "bg-purple-500",
    defaultPrompt: `You are {{agent_name}}, a lead qualification specialist for {{company_name}}.

Your goal:
- Understand the caller's needs and budget
- Qualify them based on defined criteria
- Collect contact information for follow-up
- Score leads based on responses

Qualification questions:
1. "What brings you to {{company_name}} today?"
2. "What's your timeline for [making a decision/getting started]?"
3. "Have you worked with [similar services] before?"
4. "What's your budget range for this project?"
5. "Who else is involved in the decision-making process?"

Scoring criteria:
- High priority: Immediate need + budget confirmed + decision maker
- Medium priority: 30-day timeline OR budget to confirm
- Low priority: Just researching, no timeline

Always be helpful even for low-priority leads - they may convert later!`,
    capabilities: {
      answer_calls: true,
      make_calls: true,
      schedule_appointments: false,
      send_confirmations: false,
      take_messages: true,
      transfer_calls: true,
      qualify_leads: true,
    },
  },
];

// Preset tools - tools with comingSoon: true are not yet wired to backend
const PRESET_TOOLS = [
  { id: "check_availability", name: "Check Calendar Availability", description: "Query your calendar to find open time slots for appointments", icon: Calendar, requires: "Google Calendar or Microsoft 365", comingSoon: true },
  { id: "book_appointment", name: "Book Appointment", description: "Create calendar events with attendee details and send automatic invites", icon: Calendar, requires: "Google Calendar or Microsoft 365", comingSoon: true },
  { id: "send_email", name: "Send Email Confirmation", description: "Send appointment confirmations, follow-ups, or custom emails to callers", icon: Mail, requires: "Gmail or Outlook", comingSoon: true },
  { id: "send_sms", name: "Send SMS", description: "Send text message confirmations or reminders to caller's phone", icon: MessageSquare, requires: "Twilio", comingSoon: true },
  { id: "transfer_call", name: "Transfer to Human", description: "Hand off the call to a human agent when needed (e.g., complex requests)", icon: Users, requires: "Twilio", comingSoon: false },
  { id: "take_message", name: "Take Message", description: "Record caller's name, contact info, and message for later follow-up", icon: MessageSquare, requires: null, comingSoon: false },
];

// Webhook events
const WEBHOOK_EVENTS = [
  { value: "call.started", label: "Call Started", description: "When a call begins" },
  { value: "call.ended", label: "Call Ended", description: "When a call ends" },
  { value: "call.transferred", label: "Call Transferred", description: "When a call is transferred" },
  { value: "appointment.booked", label: "Appointment Booked", description: "When an appointment is scheduled" },
  { value: "appointment.cancelled", label: "Appointment Cancelled", description: "When an appointment is cancelled" },
  { value: "message.taken", label: "Message Taken", description: "When a message is recorded" },
  { value: "lead.qualified", label: "Lead Qualified", description: "When a lead is scored" },
];

// Wizard steps
const WIZARD_STEPS = [
  { id: "type", label: "Agent Type", icon: Bot },
  { id: "identity", label: "Identity", icon: Users },
  { id: "voice", label: "Voice", icon: Volume2 },
  { id: "prompt", label: "Instructions", icon: FileText },
  { id: "tools", label: "Tools", icon: Settings2 },
  { id: "knowledge", label: "Knowledge", icon: Globe },
  { id: "test", label: "Test", icon: PhoneCall },
  { id: "review", label: "Review", icon: Check },
];

interface CustomVariable {
  name: string;
  defaultValue: string;
}

interface UploadedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  content: string;
  status: "uploading" | "processing" | "ready" | "error";
  progress: number;
}

interface AgentFormData {
  name: string;
  type: "receptionist" | "scheduler" | "reminder" | "qualifier";
  status: string;
  company_id: string;
  persona: {
    display_name: string;
    role: string;
    greeting: string;
    personality: string[];
    system_prompt: string;
  };
  voice: {
    voice_id: string;
    speed: number;
    stability: number;
    style: number;
  };
  capabilities: {
    answer_calls: boolean;
    make_calls: boolean;
    schedule_appointments: boolean;
    send_confirmations: boolean;
    take_messages: boolean;
    transfer_calls: boolean;
    qualify_leads: boolean;
  };
  preset_tools: Record<string, boolean>;
  custom_tools: Array<{
    id: string;
    name: string;
    description: string;
    endpoint: string;
    method: string;
    enabled: boolean;
  }>;
  webhooks: Array<{
    id: string;
    event: string;
    url: string;
    enabled: boolean;
  }>;
  knowledge_base: Array<{
    id: string;
    type: "faq" | "document" | "website";
    title: string;
    content: string;
    source_url?: string;
  }>;
  uploaded_files: UploadedFile[];
  custom_variables: CustomVariable[];
}

// Initial form state for change detection
const getInitialFormData = (): AgentFormData => ({
  name: "",
  type: "receptionist",
  status: "draft",
  company_id: "",
  persona: {
    display_name: "",
    role: "Virtual Assistant",
    greeting: "Hello! Thank you for calling. How may I assist you today?",
    personality: ["friendly", "professional"],
    system_prompt: AGENT_TEMPLATES[0].defaultPrompt,
  },
  voice: {
    voice_id: "NATF0",
    speed: 1.0,
    stability: 0.75,
    style: 0.5,
  },
  capabilities: { ...AGENT_TEMPLATES[0].capabilities },
  preset_tools: {
    check_availability: false,
    book_appointment: false,
    send_email: false,
    send_sms: false,
    transfer_call: true,
    take_message: true,
  },
  custom_tools: [],
  webhooks: [],
  knowledge_base: [],
  uploaded_files: [],
  custom_variables: [
    { name: "company_name", defaultValue: "" },
    { name: "business_hours", defaultValue: "Monday-Friday 9am-5pm" },
    { name: "services", defaultValue: "" },
  ],
});

export default function CreateAgentPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Form data and change tracking
  const [formData, setFormData] = useState<AgentFormData>(getInitialFormData());
  const [initialFormData] = useState<AgentFormData>(getInitialFormData());
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  // Unsaved changes modal
  const [showUnsavedModal, setShowUnsavedModal] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);

  // PersonaPlex connection status
  const [personaplexStatus, setPersonaplexStatus] = useState<"checking" | "connected" | "disconnected">("checking");
  const [isPlayingVoice, setIsPlayingVoice] = useState(false);
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState("Hello! Thank you for calling. How may I assist you today?");

  // AI Copilot
  const [showCopilotModal, setShowCopilotModal] = useState(false);
  const [copilotDescription, setCopilotDescription] = useState("");
  const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);
  const [copilotError, setCopilotError] = useState("");

  // Backend/Twilio status
  const [backendStatus, setBackendStatus] = useState<"checking" | "connected" | "disconnected">("checking");
  const [twilioConfigured, setTwilioConfigured] = useState(false);
  const [testCallPhoneNumber, setTestCallPhoneNumber] = useState("");

  // Drag and drop
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Companies
  const [companies, setCompanies] = useState<Array<{ id: string; name: string }>>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);

  // Fetch companies on mount
  useEffect(() => {
    const fetchCompanies = async () => {
      try {
        const response = await api.get("/companies");
        const companyList = response.data.items || [];
        setCompanies(companyList);
        // Auto-select first company if available
        if (companyList.length > 0 && !formData.company_id) {
          setFormData(prev => ({ ...prev, company_id: companyList[0].id }));
        }
      } catch (err) {
        console.error("Failed to fetch companies:", err);
      } finally {
        setCompaniesLoading(false);
      }
    };
    fetchCompanies();
  }, []);

  // Check for unsaved changes
  useEffect(() => {
    const hasChanges = JSON.stringify(formData) !== JSON.stringify(initialFormData);
    setHasUnsavedChanges(hasChanges);
  }, [formData, initialFormData]);

  // Warn before leaving page with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = "";
        return "";
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedChanges]);

  // Check PersonaPlex and Twilio connection on mount
  // NOTE: Uses /settings/integrations (user settings) NOT /integrations (OAuth status)
  useEffect(() => {
    const checkIntegrations = async () => {
      try {
        // First verify we're authenticated
        await api.get("/auth/me");
        setBackendStatus("connected");

        // Get all integration settings from the single source of truth
        const response = await api.get("/settings/integrations");
        const data = response.data;

        // Check PersonaPlex connection status
        if (data?.personaplex?.connected) {
          setPersonaplexStatus("connected");
        } else {
          setPersonaplexStatus("disconnected");
        }

        // Check Twilio configuration status
        setTwilioConfigured(data?.twilio?.connected || false);
      } catch {
        setBackendStatus("disconnected");
        setPersonaplexStatus("disconnected");
        setTwilioConfigured(false);
      }
    };

    checkIntegrations();
  }, []);

  // Update form data helper
  const updateFormData = useCallback((field: string, value: unknown) => {
    setFormData(prev => {
      const keys = field.split(".");
      if (keys.length === 1) {
        return { ...prev, [field]: value };
      }

      const newData = { ...prev };
      let current: Record<string, unknown> = newData;
      for (let i = 0; i < keys.length - 1; i++) {
        current[keys[i]] = { ...(current[keys[i]] as Record<string, unknown>) };
        current = current[keys[i]] as Record<string, unknown>;
      }
      current[keys[keys.length - 1]] = value;
      return newData;
    });
  }, []);

  // Handle template selection
  const handleTemplateSelect = (template: typeof AGENT_TEMPLATES[0]) => {
    setFormData(prev => ({
      ...prev,
      type: template.type as AgentFormData["type"],
      capabilities: { ...template.capabilities },
      persona: {
        ...prev.persona,
        system_prompt: template.defaultPrompt,
      },
    }));
  };

  // Handle step navigation with unsaved changes check
  const handleStepClick = (stepIndex: number) => {
    setCurrentStep(stepIndex);
  };

  // Handle navigation away with unsaved changes
  const handleNavigateAway = (navigateFn: () => void) => {
    if (hasUnsavedChanges) {
      setPendingNavigation(() => navigateFn);
      setShowUnsavedModal(true);
    } else {
      navigateFn();
    }
  };

  // Voice preview via PersonaPlex
  const handleVoicePreview = async (voiceId: string) => {
    if (personaplexStatus !== "connected") {
      setError("PersonaPlex not connected. Configure it in Settings → Integrations.");
      return;
    }

    if (isPlayingVoice && playingVoiceId === voiceId) {
      setIsPlayingVoice(false);
      setPlayingVoiceId(null);
      return;
    }

    setIsPlayingVoice(true);
    setPlayingVoiceId(voiceId);

    try {
      // Call PersonaPlex API to generate audio (use long timeout for TTS)
      const response = await apiLongRunning.post("/voice/preview", {
        voice_id: voiceId,
        text: previewText,
        speed: formData.voice.speed,
        stability: formData.voice.stability,
        style: formData.voice.style,
      });

      // Backend returns audio_base64, convert to playable data URL
      if (response.data.audio_base64) {
        const audioUrl = `data:audio/wav;base64,${response.data.audio_base64}`;
        const audio = new Audio(audioUrl);
        audio.onended = () => {
          setIsPlayingVoice(false);
          setPlayingVoiceId(null);
        };
        audio.onerror = () => {
          setIsPlayingVoice(false);
          setPlayingVoiceId(null);
          setError("Failed to play audio preview.");
        };
        audio.play();
      } else {
        setIsPlayingVoice(false);
        setPlayingVoiceId(null);
        setError("No audio data received from server.");
      }
    } catch (err) {
      console.error("Voice preview error:", err);
      setError("Failed to generate voice preview. Check PersonaPlex connection.");
      setIsPlayingVoice(false);
      setPlayingVoiceId(null);
    }
  };

  // AI Copilot - generate prompt via Claude
  const handleGeneratePrompt = async () => {
    if (!copilotDescription.trim()) {
      setCopilotError("Please describe your business and what you want the agent to do.");
      return;
    }

    // Minimum length validation (backend requires 10+ characters)
    if (copilotDescription.trim().length < 10) {
      setCopilotError("Please provide more detail about your business (at least 10 characters).");
      return;
    }

    setCopilotError("");
    setIsGeneratingPrompt(true);

    try {
      const response = await api.post("/agents/generate-prompt", {
        agent_type: formData.type,
        business_description: copilotDescription,
        company_name: formData.custom_variables.find(v => v.name === "company_name")?.defaultValue || null,
        additional_context: null,
      });

      updateFormData("persona.system_prompt", response.data.prompt);

      // Add discovered variables
      if (response.data.variables?.length > 0) {
        const existingVarNames = formData.custom_variables.map(v => v.name);
        const newVars = response.data.variables
          .filter((v: string) => !existingVarNames.includes(v))
          .map((v: string) => ({ name: v, defaultValue: "" }));

        if (newVars.length > 0) {
          setFormData(prev => ({
            ...prev,
            custom_variables: [...prev.custom_variables, ...newVars],
          }));
        }
      }

      setShowCopilotModal(false);
      setCopilotDescription("");
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosError = err as { response?: { status?: number; data?: { detail?: { detail?: string; code?: string } | string } } };
        const status = axiosError.response?.status;
        const detail = axiosError.response?.data?.detail;

        // Handle specific error cases with user-friendly messages
        if (status === 503) {
          setCopilotError("AI Copilot requires an Anthropic API key. Configure it in Settings -> Integrations -> Anthropic.");
        } else if (status === 401) {
          setCopilotError("Invalid Anthropic API key. Please check your API key in Settings -> Integrations -> Anthropic.");
        } else if (typeof detail === "object" && detail?.code === "AI_NOT_CONFIGURED") {
          setCopilotError("AI Copilot requires an Anthropic API key. Configure it in Settings -> Integrations -> Anthropic.");
        } else if (typeof detail === "object" && detail?.detail) {
          setCopilotError(detail.detail);
        } else if (typeof detail === "string") {
          setCopilotError(detail);
        } else {
          setCopilotError("Failed to generate prompt. Please try again.");
        }
      } else {
        setCopilotError("Failed to generate prompt. Is the backend running?");
      }
    } finally {
      setIsGeneratingPrompt(false);
    }
  };

  // Custom variables
  const addCustomVariable = () => {
    setFormData(prev => ({
      ...prev,
      custom_variables: [...prev.custom_variables, { name: "", defaultValue: "" }],
    }));
  };

  const updateCustomVariable = (index: number, field: "name" | "defaultValue", value: string) => {
    setFormData(prev => {
      const newVars = [...prev.custom_variables];
      newVars[index] = { ...newVars[index], [field]: value };
      return { ...prev, custom_variables: newVars };
    });
  };

  const removeCustomVariable = (index: number) => {
    setFormData(prev => ({
      ...prev,
      custom_variables: prev.custom_variables.filter((_, i) => i !== index),
    }));
  };

  const insertVariable = (varName: string) => {
    const variable = `{{${varName}}}`;
    updateFormData("persona.system_prompt", formData.persona.system_prompt + " " + variable);
  };

  // File drag and drop handlers
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    await processFiles(files);
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files);
      await processFiles(files);
    }
  };

  const processFiles = async (files: File[]) => {
    const allowedTypes = [
      "application/pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "text/plain",
      "text/csv",
    ];

    for (const file of files) {
      if (!allowedTypes.includes(file.type) && !file.name.endsWith(".txt") && !file.name.endsWith(".csv")) {
        setError(`File type not supported: ${file.name}. Use PDF, DOCX, TXT, or CSV.`);
        continue;
      }

      const fileId = `file_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const newFile: UploadedFile = {
        id: fileId,
        name: file.name,
        size: file.size,
        type: file.type,
        content: "",
        status: "uploading",
        progress: 0,
      };

      setFormData(prev => ({
        ...prev,
        uploaded_files: [...prev.uploaded_files, newFile],
      }));

      // Simulate upload progress and extract text
      try {
        // Update progress
        for (let i = 0; i <= 100; i += 20) {
          await new Promise(resolve => setTimeout(resolve, 100));
          setFormData(prev => ({
            ...prev,
            uploaded_files: prev.uploaded_files.map(f =>
              f.id === fileId ? { ...f, progress: i, status: i < 100 ? "uploading" : "processing" } : f
            ),
          }));
        }

        // Read file content
        let content = "";
        if (file.type === "text/plain" || file.name.endsWith(".txt") || file.name.endsWith(".csv")) {
          content = await file.text();
        } else {
          // For PDF/DOCX, we'd need backend processing
          // For now, show that it needs backend
          content = `[Content from ${file.name} - requires backend text extraction]`;
        }

        // Update with extracted content
        setFormData(prev => ({
          ...prev,
          uploaded_files: prev.uploaded_files.map(f =>
            f.id === fileId ? { ...f, content, status: "ready", progress: 100 } : f
          ),
          knowledge_base: [
            ...prev.knowledge_base,
            {
              id: fileId,
              type: "document",
              title: file.name,
              content: content.slice(0, 5000), // Limit preview
            },
          ],
        }));
      } catch (err) {
        console.error("File processing error:", err);
        setFormData(prev => ({
          ...prev,
          uploaded_files: prev.uploaded_files.map(f =>
            f.id === fileId ? { ...f, status: "error" } : f
          ),
        }));
      }
    }
  };

  const removeUploadedFile = (fileId: string) => {
    setFormData(prev => ({
      ...prev,
      uploaded_files: prev.uploaded_files.filter(f => f.id !== fileId),
      knowledge_base: prev.knowledge_base.filter(k => k.id !== fileId),
    }));
  };

  // Website scraping
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [isScrapingWebsite, setIsScrapingWebsite] = useState(false);

  // Paste text
  const [showPasteTextModal, setShowPasteTextModal] = useState(false);
  const [pasteTextTitle, setPasteTextTitle] = useState("");
  const [pasteTextContent, setPasteTextContent] = useState("");

  const handleScrapeWebsite = async () => {
    if (!websiteUrl.trim()) {
      setError("Please enter a website URL.");
      return;
    }

    setIsScrapingWebsite(true);
    setError("");

    try {
      // Call backend to scrape website
      const response = await api.post("/knowledge/scrape", { url: websiteUrl });

      if (response.data.content) {
        const newItem = {
          id: `website_${Date.now()}`,
          type: "website" as const,
          title: response.data.title || websiteUrl,
          content: response.data.content,
          source_url: websiteUrl,
        };

        setFormData(prev => ({
          ...prev,
          knowledge_base: [...prev.knowledge_base, newItem],
        }));

        setWebsiteUrl("");
      }
    } catch (err) {
      console.error("Website scraping error:", err);
      setError("Failed to scrape website. Backend may not support this yet.");
    } finally {
      setIsScrapingWebsite(false);
    }
  };

  // FAQ management
  const addFAQ = () => {
    const newFaq = {
      id: `faq_${Date.now()}`,
      type: "faq" as const,
      title: "",
      content: "",
    };
    setFormData(prev => ({
      ...prev,
      knowledge_base: [...prev.knowledge_base, newFaq],
    }));
  };

  // Paste text
  const handleAddPastedText = () => {
    if (!pasteTextContent.trim()) {
      setError("Please paste some text content.");
      return;
    }

    const newItem = {
      id: `document_${Date.now()}`,
      type: "document" as const,
      title: pasteTextTitle.trim() || "Pasted Content",
      content: pasteTextContent.trim(),
    };

    setFormData(prev => ({
      ...prev,
      knowledge_base: [...prev.knowledge_base, newItem],
    }));

    // Reset modal state
    setPasteTextTitle("");
    setPasteTextContent("");
    setShowPasteTextModal(false);
  };

  const removeKnowledgeItem = (id: string) => {
    setFormData(prev => ({
      ...prev,
      knowledge_base: prev.knowledge_base.filter(k => k.id !== id),
      uploaded_files: prev.uploaded_files.filter(f => f.id !== id),
    }));
  };

  // Custom tools
  const addCustomTool = () => {
    setFormData(prev => ({
      ...prev,
      custom_tools: [...prev.custom_tools, {
        id: `tool_${Date.now()}`,
        name: "",
        description: "",
        endpoint: "",
        method: "GET",
        enabled: true,
      }],
    }));
  };

  const removeCustomTool = (id: string) => {
    setFormData(prev => ({
      ...prev,
      custom_tools: prev.custom_tools.filter(t => t.id !== id),
    }));
  };

  // Webhooks
  const addWebhook = () => {
    setFormData(prev => ({
      ...prev,
      webhooks: [...prev.webhooks, {
        id: `webhook_${Date.now()}`,
        event: "call.ended",
        url: "",
        enabled: true,
      }],
    }));
  };

  const removeWebhook = (id: string) => {
    setFormData(prev => ({
      ...prev,
      webhooks: prev.webhooks.filter(w => w.id !== id),
    }));
  };

  // Submit form
  const handleSubmit = async () => {
    setError("");
    setIsSubmitting(true);

    try {
      if (!formData.company_id) {
        throw new Error("Please select a company first. Create one in Companies if you don't have any.");
      }
      if (!formData.name.trim()) {
        throw new Error("Agent name is required");
      }
      if (!formData.persona.display_name.trim()) {
        throw new Error("Display name is required");
      }

      // Resolve voice name from selected voice_id
      const selectedVoice = PERSONAPLEX_VOICES.find(v => v.value === formData.voice.voice_id);
      const payload = {
        name: formData.name,
        type: formData.type,
        company_id: formData.company_id,
        persona: formData.persona,
        voice: {
          ...formData.voice,
          name: selectedVoice?.label || "Default",
          pitch: 1.0,
        },
        capabilities: formData.capabilities,
        transfer_settings: {
          enabled: false,
          default_number: null,
          rules: [],
        },
        conversation_settings: {
          max_duration_seconds: 300,
          interruption_handling: "barge_in",
          end_phrase: "Thank you for calling. Have a great day!",
          silence_timeout_seconds: 10,
          language: "en",
        },
      };

      const response = await api.post("/agents", payload);
      const createdAgent = response.data;

      // Persist any knowledge base items collected during wizard
      if (formData.knowledge_base && formData.knowledge_base.length > 0) {
        const agentId = createdAgent.id;
        for (const item of formData.knowledge_base) {
          try {
            await api.post(`/agents/${agentId}/knowledge`, {
              type: item.type,
              title: item.title,
              content: item.content,
              source_url: item.source_url || null,
            });
          } catch (kbErr) {
            console.warn(`Failed to add knowledge item "${item.title}":`, kbErr);
          }
        }
      }

      // Redirect to the new agent's edit page so user can finish configuration
      router.push(`/dashboard/agents/${createdAgent.id}`);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else if (err && typeof err === "object" && "response" in err) {
        const axiosError = err as { response?: { data?: { detail?: unknown } } };
        const detail = axiosError.response?.data?.detail;
        if (typeof detail === "string") {
          setError(detail);
        } else if (detail && typeof detail === "object" && "detail" in detail) {
          setError((detail as { detail: string }).detail);
        } else {
          setError("Failed to create agent");
        }
      } else {
        setError("Failed to create agent");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Navigation
  const canProceed = () => {
    switch (currentStep) {
      case 0: return true;
      case 1: return formData.name.trim() !== "" && formData.persona.display_name.trim() !== "";
      default: return true;
    }
  };

  const nextStep = () => {
    if (currentStep < WIZARD_STEPS.length - 1 && canProceed()) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(prev => prev - 1);
    }
  };

  // Format file size
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  // Render step content
  const renderStepContent = () => {
    switch (currentStep) {
      // Step 0: Agent Type
      case 0:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Choose your agent type</h2>
              <p className="text-muted-foreground">Select a template to get started.</p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              {AGENT_TEMPLATES.map((template) => {
                const Icon = template.icon;
                const isSelected = formData.type === template.type;
                return (
                  <Card
                    key={template.type}
                    className={`cursor-pointer transition-all hover:shadow-md ${isSelected ? "ring-2 ring-primary" : ""}`}
                    onClick={() => handleTemplateSelect(template)}
                  >
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-lg ${template.color}`}>
                          <Icon className="h-5 w-5 text-white" />
                        </div>
                        <CardTitle className="text-lg">{template.name}</CardTitle>
                        {isSelected && <Check className="h-5 w-5 text-primary ml-auto" />}
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">{template.description}</p>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {Object.entries(template.capabilities)
                          .filter(([, enabled]) => enabled)
                          .map(([key]) => (
                            <Badge key={key} variant="secondary" className="text-xs">
                              {key.replace(/_/g, " ")}
                            </Badge>
                          ))}
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        );

      // Step 1: Identity
      case 1:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Agent Identity</h2>
              <p className="text-muted-foreground">Give your agent a name and persona.</p>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">Internal Name *</Label>
                <Input
                  id="name"
                  placeholder="e.g., Sarah"
                  value={formData.name}
                  onChange={(e) => updateFormData("name", e.target.value)}
                />
                <p className="text-xs text-muted-foreground">Used in your dashboard</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="display_name">Display Name *</Label>
                <Input
                  id="display_name"
                  placeholder="e.g., Sarah from Acme Corp"
                  value={formData.persona.display_name}
                  onChange={(e) => updateFormData("persona.display_name", e.target.value)}
                />
                <p className="text-xs text-muted-foreground">How the agent introduces itself</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="role">Role</Label>
                <Input
                  id="role"
                  placeholder="e.g., Virtual Receptionist"
                  value={formData.persona.role}
                  onChange={(e) => updateFormData("persona.role", e.target.value)}
                />
                <p className="text-xs text-muted-foreground">How the agent describes its position</p>
              </div>
            </div>
          </div>
        );

      // Step 2: Voice (PersonaPlex only)
      case 2:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Voice Configuration</h2>
              <p className="text-muted-foreground">
                Select your agent&apos;s voice powered by NVIDIA PersonaPlex.
              </p>
            </div>

            {/* PersonaPlex connection status */}
            {personaplexStatus !== "connected" && (
              <Card className="border-yellow-200 bg-yellow-50">
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    <AlertCircle className="h-5 w-5 text-yellow-600" />
                    <div className="flex-1">
                      <p className="font-medium text-yellow-800">PersonaPlex Not Connected</p>
                      <p className="text-sm text-yellow-700">
                        Configure PersonaPlex in Settings → Integrations to preview voices.
                      </p>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => handleNavigateAway(() => router.push("/dashboard/settings"))}>
                      <Settings2 className="h-4 w-4 mr-2" />
                      Settings
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Preview text */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Preview Text</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex gap-2">
                  <Input
                    value={previewText}
                    onChange={(e) => setPreviewText(e.target.value)}
                    placeholder="Enter text to preview..."
                    className="flex-1"
                  />
                  <Button variant="outline" onClick={() => setPreviewText(formData.persona.greeting)}>
                    Use Greeting
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Voice selection - PersonaPlex NVIDIA voices only */}
            <Tabs defaultValue="Natural" className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="Natural">PersonaPlex Natural</TabsTrigger>
                <TabsTrigger value="Variety">PersonaPlex Variety</TabsTrigger>
              </TabsList>

              {["Natural", "Variety"].map((category) => (
                <TabsContent key={category} value={category} className="mt-4">
                  <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                    {PERSONAPLEX_VOICES.filter(v => v.category === category).map((voice) => {
                      const isSelected = formData.voice.voice_id === voice.value;
                      const isPlaying = playingVoiceId === voice.value;
                      return (
                        <Card
                          key={voice.value}
                          className={`cursor-pointer transition-all hover:shadow-md relative ${isSelected ? "ring-2 ring-primary" : ""}`}
                          onClick={() => updateFormData("voice.voice_id", voice.value)}
                        >
                          <CardContent className="p-4">
                            <div className="flex items-center justify-between mb-2">
                              <span className="font-medium text-sm">{voice.label}</span>
                              <Button
                                size="sm"
                                variant={isPlaying ? "default" : "ghost"}
                                className="h-8 w-8 p-0"
                                disabled={personaplexStatus !== "connected"}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleVoicePreview(voice.value);
                                }}
                              >
                                {isPlaying ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Volume2 className="h-4 w-4" />
                                )}
                              </Button>
                            </div>
                            <p className="text-xs text-muted-foreground">{voice.description}</p>
                            <Badge variant="secondary" className="mt-2 text-xs capitalize">
                              {voice.gender}
                            </Badge>
                            {isSelected && (
                              <div className="absolute top-2 right-10">
                                <Check className="h-4 w-4 text-primary" />
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                </TabsContent>
              ))}
            </Tabs>

            {/* Voice settings */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Voice Settings</CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <Label>Speed</Label>
                    <span className="text-sm text-muted-foreground">{formData.voice.speed.toFixed(1)}x</span>
                  </div>
                  <Slider
                    value={[formData.voice.speed]}
                    onValueChange={([value]) => updateFormData("voice.speed", value)}
                    min={0.5}
                    max={1.5}
                    step={0.1}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <Label>Stability</Label>
                    <span className="text-sm text-muted-foreground">{(formData.voice.stability * 100).toFixed(0)}%</span>
                  </div>
                  <Slider
                    value={[formData.voice.stability]}
                    onValueChange={([value]) => updateFormData("voice.stability", value)}
                    min={0}
                    max={1}
                    step={0.05}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <Label>Style Exaggeration</Label>
                    <span className="text-sm text-muted-foreground">{(formData.voice.style * 100).toFixed(0)}%</span>
                  </div>
                  <Slider
                    value={[formData.voice.style]}
                    onValueChange={([value]) => updateFormData("voice.style", value)}
                    min={0}
                    max={1}
                    step={0.05}
                  />
                </div>

                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => handleVoicePreview(formData.voice.voice_id)}
                  disabled={personaplexStatus !== "connected" || isPlayingVoice}
                >
                  {isPlayingVoice ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Playing...
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      Preview Selected Voice
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>
        );

      // Step 3: Instructions
      case 3:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Agent Instructions</h2>
              <p className="text-muted-foreground">
                Define how your agent should behave.
              </p>
            </div>

            {/* AI Copilot */}
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">Need help writing instructions?</h3>
                    <p className="text-sm text-muted-foreground">
                      Describe your business and we&apos;ll generate a complete prompt.
                    </p>
                  </div>
                  <Button onClick={() => setShowCopilotModal(true)}>
                    <Wand2 className="h-4 w-4 mr-2" />
                    AI Copilot
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Custom Variables */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base">Custom Variables</CardTitle>
                    <CardDescription>Variables like {"{{company_name}}"} get replaced during calls</CardDescription>
                  </div>
                  <Button variant="outline" size="sm" onClick={addCustomVariable}>
                    <Plus className="h-4 w-4 mr-2" />
                    Add Variable
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {formData.custom_variables.map((variable, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <div className="flex-1 grid grid-cols-2 gap-2">
                        <Input
                          placeholder="Variable name"
                          value={variable.name}
                          onChange={(e) => updateCustomVariable(index, "name", e.target.value.replace(/[^a-z0-9_]/gi, "_").toLowerCase())}
                        />
                        <Input
                          placeholder="Default value"
                          value={variable.defaultValue}
                          onChange={(e) => updateCustomVariable(index, "defaultValue", e.target.value)}
                        />
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => insertVariable(variable.name)}
                        disabled={!variable.name}
                        title="Insert into prompt"
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => removeCustomVariable(index)}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Prompt editor */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base">Agent Behavior Instructions</CardTitle>
                    <CardDescription className="mt-1">
                      Define how your agent should respond, including tone, responsibilities, and conversation flow.
                      Use {"{{variables}}"} for dynamic content that changes per call.
                    </CardDescription>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => navigator.clipboard.writeText(formData.persona.system_prompt)}
                    title="Copy to clipboard"
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <Textarea
                  value={formData.persona.system_prompt}
                  onChange={(e) => updateFormData("persona.system_prompt", e.target.value)}
                  rows={20}
                  className="font-mono text-sm"
                  placeholder="Enter instructions for your agent..."
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <p className="text-xs text-muted-foreground mr-2">Quick insert:</p>
                  {formData.custom_variables.filter(v => v.name).map((variable) => (
                    <Badge
                      key={variable.name}
                      variant="outline"
                      className="cursor-pointer text-xs hover:bg-primary hover:text-primary-foreground"
                      onClick={() => insertVariable(variable.name)}
                    >
                      {`{{${variable.name}}}`}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* AI Copilot Modal */}
            <Dialog open={showCopilotModal} onOpenChange={setShowCopilotModal}>
              <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <Wand2 className="h-5 w-5" />
                    AI Copilot
                  </DialogTitle>
                  <DialogDescription>
                    Describe your business and what you want the agent to do.
                  </DialogDescription>
                </DialogHeader>

                <Textarea
                  value={copilotDescription}
                  onChange={(e) => setCopilotDescription(e.target.value)}
                  placeholder="Example: We're a dental clinic. The agent should help patients schedule appointments, answer questions about services, and provide directions."
                  rows={6}
                />

                {copilotError && (
                  <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive">
                    {copilotError}
                  </div>
                )}

                <DialogFooter>
                  <Button variant="outline" onClick={() => setShowCopilotModal(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleGeneratePrompt} disabled={isGeneratingPrompt}>
                    {isGeneratingPrompt ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-4 w-4 mr-2" />
                        Generate
                      </>
                    )}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        );

      // Step 4: Tools
      case 4:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Tools & Actions</h2>
              <p className="text-muted-foreground">Enable capabilities and connect integrations.</p>
            </div>

            {/* Preset Tools */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base">Built-in Tools</CardTitle>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger>
                        <HelpCircle className="h-4 w-4 text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="max-w-xs">Pre-configured tools your agent can use. Some require integrations.</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 md:grid-cols-2">
                  {PRESET_TOOLS.map((tool) => {
                    const Icon = tool.icon;
                    const isEnabled = formData.preset_tools[tool.id] || false;
                    const isDisabled = tool.comingSoon;
                    return (
                      <div
                        key={tool.id}
                        className={`flex items-center justify-between rounded-lg border p-4 ${
                          isDisabled
                            ? "opacity-60 bg-muted/30"
                            : isEnabled
                              ? "border-primary bg-primary/5"
                              : ""
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <div className={`p-2 rounded-lg ${isEnabled && !isDisabled ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
                            <Icon className="h-4 w-4" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="font-medium text-sm">{tool.name}</p>
                              {tool.comingSoon && (
                                <Badge variant="outline" className="text-xs px-1.5 py-0 text-muted-foreground border-muted-foreground/50">
                                  Coming Soon
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground">{tool.description}</p>
                            {tool.requires && !tool.comingSoon && (
                              <p className="text-xs text-orange-600">Requires: {tool.requires}</p>
                            )}
                          </div>
                        </div>
                        <Switch
                          checked={isEnabled && !isDisabled}
                          disabled={isDisabled}
                          onCheckedChange={(checked) => {
                            if (!isDisabled) {
                              setFormData(prev => ({
                                ...prev,
                                preset_tools: { ...prev.preset_tools, [tool.id]: checked },
                              }));
                            }
                          }}
                        />
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>

            {/* Custom Tools */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-base">Custom Tools</CardTitle>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <HelpCircle className="h-4 w-4 text-muted-foreground" />
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="max-w-xs">Connect your own APIs. Example: Check order status, update CRM.</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <Button variant="outline" size="sm" onClick={addCustomTool}>
                    <Plus className="h-4 w-4 mr-2" />
                    Add Tool
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {formData.custom_tools.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground border-2 border-dashed rounded-lg">
                    <Webhook className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No custom tools yet</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {formData.custom_tools.map((tool, index) => (
                      <div key={tool.id} className="border rounded-lg p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <Input
                            placeholder="Tool name"
                            value={tool.name}
                            onChange={(e) => {
                              const newTools = [...formData.custom_tools];
                              newTools[index].name = e.target.value;
                              updateFormData("custom_tools", newTools);
                            }}
                            className="max-w-xs"
                          />
                          <div className="flex gap-2">
                            <Button variant="outline" size="sm" disabled>
                              Test Tool
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => removeCustomTool(tool.id)}>
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </div>
                        <Input
                          placeholder="Description"
                          value={tool.description}
                          onChange={(e) => {
                            const newTools = [...formData.custom_tools];
                            newTools[index].description = e.target.value;
                            updateFormData("custom_tools", newTools);
                          }}
                        />
                        <div className="flex gap-2">
                          <select
                            value={tool.method}
                            onChange={(e) => {
                              const newTools = [...formData.custom_tools];
                              newTools[index].method = e.target.value;
                              updateFormData("custom_tools", newTools);
                            }}
                            className="h-10 rounded-md border px-3 py-2 text-sm bg-background"
                          >
                            <option value="GET">GET</option>
                            <option value="POST">POST</option>
                          </select>
                          <Input
                            placeholder="https://api.example.com/endpoint"
                            value={tool.endpoint}
                            onChange={(e) => {
                              const newTools = [...formData.custom_tools];
                              newTools[index].endpoint = e.target.value;
                              updateFormData("custom_tools", newTools);
                            }}
                            className="flex-1"
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Webhooks */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-base">Webhooks</CardTitle>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <HelpCircle className="h-4 w-4 text-muted-foreground" />
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="max-w-xs">Get notified when events happen. Send to Zapier, Slack, or your CRM.</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <Button variant="outline" size="sm" onClick={addWebhook}>
                    <Plus className="h-4 w-4 mr-2" />
                    Add Webhook
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {formData.webhooks.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground border-2 border-dashed rounded-lg">
                    <Zap className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No webhooks configured</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {formData.webhooks.map((webhook, index) => (
                      <div key={webhook.id} className="flex items-start gap-2 p-3 border rounded-lg">
                        <div className="flex-1 space-y-2">
                          <select
                            value={webhook.event}
                            onChange={(e) => {
                              const newWebhooks = [...formData.webhooks];
                              newWebhooks[index].event = e.target.value;
                              updateFormData("webhooks", newWebhooks);
                            }}
                            className="h-10 w-full rounded-md border px-3 py-2 text-sm bg-background"
                          >
                            {WEBHOOK_EVENTS.map((event) => (
                              <option key={event.value} value={event.value}>
                                {event.label} - {event.description}
                              </option>
                            ))}
                          </select>
                          <Input
                            placeholder="https://hooks.zapier.com/..."
                            value={webhook.url}
                            onChange={(e) => {
                              const newWebhooks = [...formData.webhooks];
                              newWebhooks[index].url = e.target.value;
                              updateFormData("webhooks", newWebhooks);
                            }}
                          />
                        </div>
                        <div className="flex items-center gap-2 pt-1">
                          <Switch
                            checked={webhook.enabled}
                            onCheckedChange={(checked) => {
                              const newWebhooks = [...formData.webhooks];
                              newWebhooks[index].enabled = checked;
                              updateFormData("webhooks", newWebhooks);
                            }}
                          />
                          <Button variant="ghost" size="sm" onClick={() => removeWebhook(webhook.id)}>
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        );

      // Step 5: Knowledge Base (with drag-drop)
      case 5:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Knowledge Base</h2>
              <p className="text-muted-foreground">
                Add documents, FAQs, or websites for your agent to reference.
              </p>
            </div>

            {/* Drag and drop upload */}
            <div
              className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                isDragging ? "border-primary bg-primary/5" : "border-muted-foreground/25"
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.csv"
                className="hidden"
                onChange={handleFileSelect}
              />
              <Upload className="h-10 w-10 mx-auto mb-4 text-muted-foreground" />
              <p className="font-medium mb-1">Drag files here or click to upload</p>
              <p className="text-sm text-muted-foreground mb-4">
                Supports PDF, DOCX, TXT, CSV files
              </p>
              <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
                <Upload className="h-4 w-4 mr-2" />
                Select Files
              </Button>
            </div>

            {/* Uploaded files */}
            {formData.uploaded_files.length > 0 && (
              <div className="space-y-2">
                <Label>Uploaded Files</Label>
                <div className="space-y-2">
                  {formData.uploaded_files.map((file) => (
                    <div key={file.id} className="flex items-center gap-3 p-3 border rounded-lg">
                      <File className="h-8 w-8 text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{file.name}</p>
                        <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                        {file.status === "uploading" && (
                          <div className="mt-1 h-1 bg-muted rounded-full overflow-hidden">
                            <div className="h-full bg-primary transition-all" style={{ width: `${file.progress}%` }} />
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {file.status === "ready" && <CheckCircle2 className="h-4 w-4 text-green-600" />}
                        {file.status === "error" && <XCircle className="h-4 w-4 text-red-600" />}
                        {file.status === "processing" && <Loader2 className="h-4 w-4 animate-spin" />}
                        <Button variant="ghost" size="sm" onClick={() => removeUploadedFile(file.id)}>
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Add website or paste text */}
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Globe className="h-4 w-4" />
                    Add Website
                  </CardTitle>
                  <CardDescription>Import content from a webpage</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2">
                    <Input
                      placeholder="https://example.com/faq"
                      value={websiteUrl}
                      onChange={(e) => setWebsiteUrl(e.target.value)}
                      className="flex-1"
                    />
                    <Button variant="outline" onClick={handleScrapeWebsite} disabled={isScrapingWebsite}>
                      {isScrapingWebsite ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Link className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    Paste Text
                  </CardTitle>
                  <CardDescription>Paste text from documents, websites, or notes</CardDescription>
                </CardHeader>
                <CardContent>
                  <Button variant="outline" className="w-full" onClick={() => setShowPasteTextModal(true)}>
                    <Plus className="h-4 w-4 mr-2" />
                    Paste Content
                  </Button>
                </CardContent>
              </Card>
            </div>

            {/* Paste Text Modal */}
            <Dialog open={showPasteTextModal} onOpenChange={setShowPasteTextModal}>
              <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <FileText className="h-5 w-5" />
                    Paste Text Content
                  </DialogTitle>
                  <DialogDescription>
                    Paste content from documents, websites, or notes. Your agent will use this as reference.
                  </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                  <div>
                    <Label htmlFor="paste-title">Title (optional)</Label>
                    <Input
                      id="paste-title"
                      placeholder="e.g., Company Policies, Product Info"
                      value={pasteTextTitle}
                      onChange={(e) => setPasteTextTitle(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="paste-content">Content</Label>
                    <Textarea
                      id="paste-content"
                      placeholder="Paste your text content here..."
                      value={pasteTextContent}
                      onChange={(e) => setPasteTextContent(e.target.value)}
                      rows={10}
                      className="mt-1"
                    />
                  </div>
                </div>

                <DialogFooter>
                  <Button variant="outline" onClick={() => setShowPasteTextModal(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleAddPastedText} disabled={!pasteTextContent.trim()}>
                    <Plus className="h-4 w-4 mr-2" />
                    Add Content
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            {/* Add FAQ */}
            <div className="flex justify-between items-center">
              <Label>FAQs & Manual Content</Label>
              <Button variant="outline" size="sm" onClick={addFAQ}>
                <Plus className="h-4 w-4 mr-2" />
                Add FAQ
              </Button>
            </div>

            {/* Knowledge items */}
            {formData.knowledge_base.map((item) => (
              <Card key={item.id}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <Badge variant="secondary" className="capitalize">{item.type}</Badge>
                    <Button variant="ghost" size="sm" onClick={() => removeKnowledgeItem(item.id)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Input
                    placeholder="Title"
                    value={item.title}
                    onChange={(e) => {
                      const newKb = [...formData.knowledge_base];
                      const kbIndex = newKb.findIndex(k => k.id === item.id);
                      if (kbIndex >= 0) {
                        newKb[kbIndex].title = e.target.value;
                        updateFormData("knowledge_base", newKb);
                      }
                    }}
                  />
                  <Textarea
                    placeholder="Q: What are your hours?\nA: We're open 9am-5pm Monday through Friday."
                    value={item.content}
                    onChange={(e) => {
                      const newKb = [...formData.knowledge_base];
                      const kbIndex = newKb.findIndex(k => k.id === item.id);
                      if (kbIndex >= 0) {
                        newKb[kbIndex].content = e.target.value;
                        updateFormData("knowledge_base", newKb);
                      }
                    }}
                    rows={4}
                  />
                </CardContent>
              </Card>
            ))}

            {formData.knowledge_base.length === 0 && formData.uploaded_files.length === 0 && (
              <div className="text-center py-8 text-muted-foreground">
                <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>No knowledge added yet</p>
              </div>
            )}
          </div>
        );

      // Step 6: Test (no fake data)
      case 6:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Test Your Agent</h2>
              <p className="text-muted-foreground">Test before deploying.</p>
            </div>

            {/* Connection status */}
            <div className="grid gap-4 md:grid-cols-2">
              <Card className={personaplexStatus === "connected" ? "border-green-200 bg-green-50" : "border-yellow-200 bg-yellow-50"}>
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    {personaplexStatus === "connected" ? (
                      <CheckCircle2 className="h-5 w-5 text-green-600" />
                    ) : (
                      <XCircle className="h-5 w-5 text-yellow-600" />
                    )}
                    <div>
                      <p className="font-medium">PersonaPlex</p>
                      <p className="text-sm text-muted-foreground">
                        {personaplexStatus === "connected" ? "Connected" : "Not configured"}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className={twilioConfigured ? "border-green-200 bg-green-50" : "border-yellow-200 bg-yellow-50"}>
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    {twilioConfigured ? (
                      <CheckCircle2 className="h-5 w-5 text-green-600" />
                    ) : (
                      <XCircle className="h-5 w-5 text-yellow-600" />
                    )}
                    <div>
                      <p className="font-medium">Twilio</p>
                      <p className="text-sm text-muted-foreground">
                        {twilioConfigured ? "Connected" : "Not configured"}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              {/* Browser Test */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <Headphones className="h-5 w-5" />
                    Browser Test Call
                  </CardTitle>
                  <CardDescription>Talk to your agent in your browser</CardDescription>
                </CardHeader>
                <CardContent>
                  {personaplexStatus !== "connected" ? (
                    <div className="text-center py-6 border-2 border-dashed rounded-lg">
                      <Mic className="h-8 w-8 mx-auto mb-3 text-muted-foreground" />
                      <p className="font-medium text-muted-foreground">PersonaPlex Required</p>
                      <p className="text-sm text-muted-foreground mt-1">
                        Configure PersonaPlex in Settings to enable browser testing.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => handleNavigateAway(() => router.push("/dashboard/settings"))}
                      >
                        Go to Settings
                      </Button>
                    </div>
                  ) : (
                    <Button className="w-full" size="lg">
                      <Mic className="h-4 w-4 mr-2" />
                      Start Test Call
                    </Button>
                  )}
                </CardContent>
              </Card>

              {/* Phone Test */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <PhoneCall className="h-5 w-5" />
                    Phone Test Call
                  </CardTitle>
                  <CardDescription>Receive a test call on your phone</CardDescription>
                </CardHeader>
                <CardContent>
                  {!twilioConfigured ? (
                    <div className="text-center py-6 border-2 border-dashed rounded-lg">
                      <Phone className="h-8 w-8 mx-auto mb-3 text-muted-foreground" />
                      <p className="font-medium text-muted-foreground">Twilio Required</p>
                      <p className="text-sm text-muted-foreground mt-1">
                        Add Twilio credentials in Settings to enable phone testing.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => handleNavigateAway(() => router.push("/dashboard/settings"))}
                      >
                        Go to Settings
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <Input
                        placeholder="+1 (555) 123-4567"
                        value={testCallPhoneNumber}
                        onChange={(e) => setTestCallPhoneNumber(e.target.value)}
                      />
                      <Button className="w-full" variant="outline">
                        <Phone className="h-4 w-4 mr-2" />
                        Call My Phone
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Testing tips */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Testing Tips</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-start gap-2">
                    <Check className="h-4 w-4 mt-0.5 text-green-600 flex-shrink-0" />
                    Deploy your agent first, then test with real calls
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-4 w-4 mt-0.5 text-green-600 flex-shrink-0" />
                    Use voice preview on the Voice page to hear how it sounds
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-4 w-4 mt-0.5 text-green-600 flex-shrink-0" />
                    Check call logs after testing to review conversations
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>
        );

      // Step 7: Review
      case 7:
        // Check for configuration warnings
        const configWarnings: Array<{ message: string; severity: "warning" | "error" }> = [];

        if (!formData.name.trim()) {
          configWarnings.push({ message: "Agent name is required", severity: "error" });
        }
        if (!formData.persona.display_name.trim()) {
          configWarnings.push({ message: "Display name is recommended for caller-facing interactions", severity: "warning" });
        }
        if (!formData.persona.system_prompt.trim() || formData.persona.system_prompt.length < 50) {
          configWarnings.push({ message: "Behavior instructions should be more detailed (at least 50 characters)", severity: "warning" });
        }
        if (personaplexStatus !== "connected") {
          configWarnings.push({ message: "PersonaPlex is not configured - voice calls will not work", severity: "warning" });
        }
        if (!twilioConfigured) {
          configWarnings.push({ message: "Twilio is not configured - phone calls will not work", severity: "warning" });
        }
        // Check if calendar tools are enabled but no calendar integration
        const hasCalendarTools = formData.preset_tools.check_availability || formData.preset_tools.book_appointment;
        if (hasCalendarTools) {
          configWarnings.push({ message: "Calendar tools enabled - make sure Google Calendar or Microsoft 365 is connected", severity: "warning" });
        }
        // Check if email tools are enabled
        if (formData.preset_tools.send_email) {
          configWarnings.push({ message: "Email tool enabled - make sure Gmail or Outlook is connected", severity: "warning" });
        }

        const hasErrors = configWarnings.some(w => w.severity === "error");
        const hasWarnings = configWarnings.length > 0;

        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-semibold mb-2">Review & Deploy</h2>
              <p className="text-muted-foreground">Review your configuration before deploying.</p>
            </div>

            {/* Configuration Warnings */}
            {hasWarnings && (
              <Card className={hasErrors ? "border-red-200 bg-red-50" : "border-yellow-200 bg-yellow-50"}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    <AlertTriangle className={`h-5 w-5 ${hasErrors ? "text-red-600" : "text-yellow-600"}`} />
                    {hasErrors ? "Configuration Issues" : "Configuration Warnings"}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {configWarnings.map((warning, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-sm">
                        {warning.severity === "error" ? (
                          <XCircle className="h-4 w-4 mt-0.5 text-red-600 flex-shrink-0" />
                        ) : (
                          <AlertCircle className="h-4 w-4 mt-0.5 text-yellow-600 flex-shrink-0" />
                        )}
                        <span className={warning.severity === "error" ? "text-red-800" : "text-yellow-800"}>
                          {warning.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}

            {/* All Good Message */}
            {!hasWarnings && (
              <Card className="border-green-200 bg-green-50">
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                    <div>
                      <p className="font-medium text-green-800">Configuration looks good!</p>
                      <p className="text-sm text-green-700">Your agent is ready to deploy.</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Identity</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Name</span>
                    <span className="font-medium">{formData.name || "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Display Name</span>
                    <span className="font-medium">{formData.persona.display_name || "—"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Type</span>
                    <Badge variant="secondary" className="capitalize">{formData.type}</Badge>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Voice</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Voice</span>
                    <span className="font-medium">
                      {PERSONAPLEX_VOICES.find(v => v.value === formData.voice.voice_id)?.label}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Speed</span>
                    <span className="font-medium">{formData.voice.speed}x</span>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Tools</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(formData.preset_tools)
                      .filter(([, enabled]) => enabled)
                      .map(([key]) => {
                        const tool = PRESET_TOOLS.find(t => t.id === key);
                        return <Badge key={key} variant="secondary">{tool?.name || key}</Badge>;
                      })}
                    {Object.values(formData.preset_tools).every(v => !v) && (
                      <span className="text-muted-foreground text-sm">None enabled</span>
                    )}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Knowledge</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Documents</span>
                    <span className="font-medium">{formData.uploaded_files.length}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">FAQs</span>
                    <span className="font-medium">{formData.knowledge_base.filter(k => k.type === "faq").length}</span>
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Behavior Instructions Preview</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-sm bg-muted p-4 rounded-md overflow-auto max-h-48 whitespace-pre-wrap font-mono">
                  {formData.persona.system_prompt.slice(0, 500)}
                  {formData.persona.system_prompt.length > 500 && "..."}
                </pre>
              </CardContent>
            </Card>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <TooltipProvider>
      <div className="min-h-screen pb-24">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-background border-b px-6 py-4">
          <div className="flex items-center justify-between max-w-6xl mx-auto">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleNavigateAway(() => router.back())}
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back
              </Button>
              <div className="h-6 w-px bg-border" />
              <h1 className="text-xl font-semibold">Create Agent</h1>
              {hasUnsavedChanges && (
                <Badge variant="outline" className="text-orange-600 border-orange-300">
                  Unsaved changes
                </Badge>
              )}
            </div>
            <span className="text-sm text-muted-foreground">
              Step {currentStep + 1} of {WIZARD_STEPS.length}
            </span>
          </div>
        </div>

        {/* Progress steps - ALL CLICKABLE */}
        <div className="border-b bg-muted/30">
          <div className="max-w-6xl mx-auto px-6 py-4">
            <div className="flex items-center justify-between overflow-x-auto">
              {WIZARD_STEPS.map((step, index) => {
                const Icon = step.icon;
                const isActive = index === currentStep;
                const isCompleted = index < currentStep;

                return (
                  <div key={step.id} className="flex items-center">
                    <button
                      onClick={() => handleStepClick(index)}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors whitespace-nowrap ${
                        isActive
                          ? "bg-primary text-primary-foreground"
                          : isCompleted
                          ? "bg-primary/10 text-primary hover:bg-primary/20"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      <span className="text-sm font-medium hidden md:inline">{step.label}</span>
                    </button>
                    {index < WIZARD_STEPS.length - 1 && (
                      <ChevronRight className="h-4 w-4 mx-2 text-muted-foreground flex-shrink-0" />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Error message */}
        {error && (
          <div className="max-w-6xl mx-auto px-6 mt-4">
            <div className="rounded-md bg-destructive/15 p-4 text-sm text-destructive flex items-center gap-2">
              <AlertCircle className="h-4 w-4" />
              {error}
              <Button variant="ghost" size="sm" className="ml-auto h-6 px-2" onClick={() => setError("")}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}

        {/* Content */}
        <div className="max-w-6xl mx-auto px-6 py-8">
          {renderStepContent()}
        </div>

        {/* Footer navigation */}
        <div className="fixed bottom-0 left-0 right-0 bg-background border-t px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <Button variant="outline" onClick={prevStep} disabled={currentStep === 0}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              Previous
            </Button>

            <div className="flex gap-2">
              {currentStep < WIZARD_STEPS.length - 1 ? (
                <Button onClick={nextStep} disabled={!canProceed()}>
                  Next
                  <ArrowRight className="h-4 w-4 ml-2" />
                </Button>
              ) : (
                <Button onClick={handleSubmit} disabled={isSubmitting}>
                  {isSubmitting ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4 mr-2" />
                  )}
                  Create Agent
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Unsaved changes modal */}
        <Dialog open={showUnsavedModal} onOpenChange={setShowUnsavedModal}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-yellow-600" />
                Unsaved Changes
              </DialogTitle>
              <DialogDescription>
                You have unsaved changes. What would you like to do?
              </DialogDescription>
            </DialogHeader>
            <DialogFooter className="flex gap-2 sm:gap-0">
              <Button variant="outline" onClick={() => setShowUnsavedModal(false)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  setShowUnsavedModal(false);
                  if (pendingNavigation) {
                    pendingNavigation();
                  }
                }}
              >
                Discard
              </Button>
              <Button
                onClick={async () => {
                  await handleSubmit();
                  setShowUnsavedModal(false);
                  if (pendingNavigation) {
                    pendingNavigation();
                  }
                }}
              >
                <Save className="h-4 w-4 mr-2" />
                Save & Continue
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
}
