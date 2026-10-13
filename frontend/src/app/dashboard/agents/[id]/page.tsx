"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, Loader2, Save, Trash2, Play, Sparkles, Plus, X, Volume2
} from "lucide-react";
import api from "@/lib/api";
import { Agent, TransferRule } from "@/types";

// ─── Voice type from /voice/voices endpoint ────────────────────────────────
interface VoiceCatalogItem {
  id: string;
  name: string;
  gender: "male" | "female";
  style: string;
  description: string;
}

// ─── Slider component ───────────────────────────────────────────────────────
function Slider({
  label,
  value,
  min,
  max,
  step,
  displayValue,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  displayValue: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <Label className="text-sm">{label}</Label>
        <span className="text-sm font-semibold text-primary">{displayValue}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-secondary rounded-lg appearance-none cursor-pointer accent-primary"
      />
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

export default function EditAgentPage() {
  const router = useRouter();
  const params = useParams();
  const agentId = params.id as string;

  const [agent, setAgent] = useState<Agent | null>(null);
  const [voices, setVoices] = useState<VoiceCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [selectedTraits, setSelectedTraits] = useState<string[]>([]);
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null);
  const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    fetchAgent();
    fetchVoices();
  }, [agentId]);

  const fetchVoices = async () => {
    try {
      const response = await api.get("/voice/voices");
      setVoices(response.data.voices || []);
    } catch {
      // Fallback: use hardcoded list if endpoint unavailable
      setVoices([
        { id: "NATF0", name: "Natural Female", gender: "female", style: "natural", description: "Warm, conversational female voice" },
        { id: "NATM0", name: "Natural Male", gender: "male", style: "natural", description: "Warm, conversational male voice" },
        { id: "PROF0", name: "Professional Female", gender: "female", style: "professional", description: "Polished, authoritative female voice" },
        { id: "PROM0", name: "Professional Male", gender: "male", style: "professional", description: "Polished, authoritative male voice" },
      ]);
    }
  };

  const fetchAgent = async () => {
    try {
      const response = await api.get(`/agents/${agentId}`);
      setAgent(response.data);
      setSelectedTraits(response.data.persona?.personality || []);
    } catch (err) {
      console.error("Failed to fetch agent:", err);
      setError("Failed to load agent");
    } finally {
      setIsLoading(false);
    }
  };

  // ─── Generic nested updater ───────────────────────────────────────────────
  const updateAgent = (field: string, value: unknown) => {
    if (!agent) return;
    setAgent((prev) => {
      if (!prev) return prev;
      const keys = field.split(".");
      if (keys.length === 1) {
        return { ...prev, [field]: value };
      }
      const [parent, child] = keys;
      const parentValue = prev[parent as keyof Agent];
      return {
        ...prev,
        [parent]: {
          ...(typeof parentValue === "object" && parentValue !== null ? parentValue : {}),
          [child]: value,
        },
      };
    });
  };

  // ─── Voice preview ────────────────────────────────────────────────────────
  const playVoicePreview = async (voiceId: string) => {
    if (previewingVoice === voiceId) return; // already playing
    setPreviewingVoice(voiceId);
    try {
      const response = await api.post("/voice/preview", {
        voice_id: voiceId,
        text: agent?.persona?.greeting || "Hello, thank you for calling. How can I assist you today?",
        speed: agent?.voice?.speed || 1.0,
        stability: agent?.voice?.stability ?? 0.5,
        style: agent?.voice?.style ?? 0.5,
      });
      const audioData = response.data.audio_base64;
      if (audioRef.current) {
        audioRef.current.pause();
      }
      const audio = new Audio(`data:audio/wav;base64,${audioData}`);
      audioRef.current = audio;
      audio.play();
      audio.onended = () => setPreviewingVoice(null);
      audio.onerror = () => setPreviewingVoice(null);
    } catch (err: unknown) {
      console.error("Voice preview failed:", err);
      setPreviewingVoice(null);
      const msg =
        err && typeof err === "object" && "response" in err
          ? (err as { response?: { data?: { detail?: { detail?: string } | string } } }).response?.data?.detail
          : undefined;
      const detail = typeof msg === "object" && msg !== null ? msg.detail : msg;
      setError(detail || "Voice preview failed. Check PersonaPlex connection in Settings.");
    }
  };

  // ─── AI prompt generation ─────────────────────────────────────────────────
  const generatePrompt = async () => {
    if (!agent) return;
    setIsGeneratingPrompt(true);
    try {
      const response = await api.post("/agents/generate-prompt", {
        agent_type: agent.type,
        business_description: `Agent named "${agent.persona?.display_name || agent.name}" with role "${agent.persona?.role || "Assistant"}". Personality: ${selectedTraits.join(", ") || "professional, helpful"}`,
        company_name: undefined,
        additional_context: agent.persona?.greeting ? `Current greeting: "${agent.persona.greeting}"` : undefined,
      });
      updateAgent("persona.system_prompt", response.data.prompt);
    } catch (err) {
      console.error("Prompt generation failed:", err);
      setError("AI prompt generation failed");
    } finally {
      setIsGeneratingPrompt(false);
    }
  };

  // ─── Personality traits ───────────────────────────────────────────────────
  const PERSONALITY_TRAITS = [
    "friendly", "professional", "empathetic", "efficient", "warm", "calm", "enthusiastic", "concise", "detailed", "humorous",
  ];

  const toggleTrait = (trait: string) => {
    setSelectedTraits((prev) =>
      prev.includes(trait) ? prev.filter((t) => t !== trait) : [...prev, trait]
    );
  };

  // ─── Transfer rules ───────────────────────────────────────────────────────
  const addTransferRule = () => {
    const rules = agent?.transfer_settings?.rules || [];
    updateAgent("transfer_settings.rules", [
      ...rules,
      { condition: "", destination: "", announce: true } as TransferRule,
    ]);
  };

  const updateTransferRule = (index: number, field: string, value: unknown) => {
    if (!agent) return;
    const rules = [...(agent.transfer_settings?.rules || [])];
    rules[index] = { ...rules[index], [field]: value };
    updateAgent("transfer_settings.rules", rules);
  };

  const removeTransferRule = (index: number) => {
    if (!agent) return;
    const rules = (agent.transfer_settings?.rules || []).filter((_, i) => i !== index);
    updateAgent("transfer_settings.rules", rules);
  };

  // ─── Save ─────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!agent) return;
    setError("");
    setSuccess("");
    setIsSaving(true);
    try {
      const payload = {
        name: agent.name,
        type: agent.type,
        persona: { ...agent.persona, personality: selectedTraits },
        voice: agent.voice,
        capabilities: agent.capabilities,
        calendar_settings: agent.calendar_settings,
        transfer_settings: agent.transfer_settings,
        conversation_settings: agent.conversation_settings,
      };
      await api.put(`/agents/${agentId}`, payload);
      setSuccess("Agent updated successfully");
      setTimeout(() => setSuccess(""), 3000);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosError = err as { response?: { data?: { detail?: string } } };
        setError(axiosError.response?.data?.detail || "Failed to update agent");
      } else {
        setError("Failed to update agent");
      }
    } finally {
      setIsSaving(false);
    }
  };

  // ─── Delete ───────────────────────────────────────────────────────────────
  const handleDelete = async () => {
    if (!confirm("Are you sure you want to delete this agent? This action cannot be undone.")) return;
    setIsDeleting(true);
    try {
      await api.delete(`/agents/${agentId}`);
      router.push("/dashboard/agents");
    } catch {
      setError("Failed to delete agent");
      setIsDeleting(false);
    }
  };

  // ─── Toggle active/paused ─────────────────────────────────────────────────
  const handleToggleStatus = async () => {
    if (!agent) return;
    try {
      const endpoint = agent.status === "active" ? "pause" : "activate";
      await api.post(`/agents/${agentId}/${endpoint}`);
      fetchAgent();
    } catch {
      setError("Failed to update agent status");
    }
  };

  // ─── Loading state ────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground">Agent not found</p>
        <Button variant="link" onClick={() => router.push("/dashboard/agents")}>Back to Agents</Button>
      </div>
    );
  }

  // Group voices by style for the selector
  const voicesByStyle = voices.reduce<Record<string, VoiceCatalogItem[]>>((acc, v) => {
    (acc[v.style] = acc[v.style] || []).push(v);
    return acc;
  }, {});

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Hidden audio element for preview playback */}
      <audio ref={audioRef} className="hidden" />

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard/agents")}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold">{agent.name}</h1>
              <Badge
                className={
                  agent.status === "active" ? "bg-green-500 text-white"
                  : agent.status === "paused" ? "bg-yellow-500 text-white"
                  : "bg-gray-500 text-white"
                }
              >
                {agent.status}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground mt-0.5">Configure your AI voice agent</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleToggleStatus}>
            {agent.status === "active" ? "Pause" : "Activate"}
          </Button>
          <Button variant="destructive" onClick={handleDelete} disabled={isDeleting}>
            {isDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {/* ── Alerts ──────────────────────────────────────────────────────────── */}
      {error && (
        <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive flex justify-between items-center">
          <span>{error}</span>
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setError("")}><X className="h-3 w-3" /></Button>
        </div>
      )}
      {success && (
        <div className="rounded-md bg-green-50 border border-green-200 p-3 text-sm text-green-800">
          {success}
        </div>
      )}

      {/* ── 1. Basic Information ────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Basic Information</CardTitle>
          <CardDescription>Agent identity and use case</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Agent Name</Label>
              <Input value={agent.name} onChange={(e) => updateAgent("name", e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Agent Type</Label>
              <Select value={agent.type} onValueChange={(v) => updateAgent("type", v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="receptionist">Receptionist</SelectItem>
                  <SelectItem value="scheduler">Scheduler</SelectItem>
                  <SelectItem value="reminder">Reminder</SelectItem>
                  <SelectItem value="qualifier">Lead Qualifier</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Display Name</Label>
              <Input
                value={agent.persona?.display_name || ""}
                onChange={(e) => updateAgent("persona.display_name", e.target.value)}
                placeholder="e.g. Sarah"
              />
            </div>
            <div className="space-y-2">
              <Label>Role / Title</Label>
              <Input
                value={agent.persona?.role || ""}
                onChange={(e) => updateAgent("persona.role", e.target.value)}
                placeholder="e.g. Virtual Receptionist"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 2. Voice Configuration ──────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Volume2 className="h-5 w-5" /> Voice Configuration
          </CardTitle>
          <CardDescription>
            Select a voice and tune the parameters. Click the play button on any voice to preview it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Voice grid grouped by style */}
          {Object.entries(voicesByStyle).map(([style, styleVoices]) => (
            <div key={style}>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                {style} voices
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {styleVoices.map((voice) => {
                  const isSelected = agent.voice?.voice_id === voice.id;
                  const isPreviewing = previewingVoice === voice.id;
                  return (
                    <div
                      key={voice.id}
                      className={`relative rounded-lg border p-3 cursor-pointer transition-all ${
                        isSelected
                          ? "border-primary bg-primary/5 shadow-sm"
                          : "border-muted hover:border-primary/40"
                      }`}
                      onClick={() => {
                        updateAgent("voice.voice_id", voice.id);
                        updateAgent("voice.name", voice.name);
                      }}
                    >
                      {isSelected && (
                        <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-primary" />
                      )}
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="text-sm font-medium">{voice.name}</p>
                          <p className="text-xs text-muted-foreground mt-0.5">{voice.description}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 mt-2">
                        <Badge variant="outline" className="text-xs">
                          {voice.gender}
                        </Badge>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0 ml-auto"
                          onClick={(e) => {
                            e.stopPropagation();
                            playVoicePreview(voice.id);
                          }}
                        >
                          {isPreviewing ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Play className="h-3 w-3" />
                          )}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}

          {/* Voice parameter sliders */}
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4 pt-2 border-t">
            <Slider
              label="Speed"
              value={agent.voice?.speed ?? 1.0}
              min={0.5}
              max={2.0}
              step={0.1}
              displayValue={`${agent.voice?.speed ?? 1.0}x`}
              onChange={(v) => updateAgent("voice.speed", v)}
            />
            <Slider
              label="Pitch"
              value={agent.voice?.pitch ?? 1.0}
              min={0.5}
              max={2.0}
              step={0.1}
              displayValue={`${agent.voice?.pitch ?? 1.0}x`}
              onChange={(v) => updateAgent("voice.pitch", v)}
            />
            <Slider
              label="Stability"
              value={agent.voice?.stability ?? 0.5}
              min={0.0}
              max={1.0}
              step={0.05}
              displayValue={(agent.voice?.stability ?? 0.5).toFixed(2)}
              onChange={(v) => updateAgent("voice.stability", v)}
            />
            <Slider
              label="Style"
              value={agent.voice?.style ?? 0.5}
              min={0.0}
              max={1.0}
              step={0.05}
              displayValue={(agent.voice?.style ?? 0.5).toFixed(2)}
              onChange={(v) => updateAgent("voice.style", v)}
            />
          </div>
        </CardContent>
      </Card>

      {/* ── 3. Persona & Behavior ───────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Persona & Behavior</CardTitle>
          <CardDescription>Define what your agent says and how it communicates</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Greeting Message</Label>
            <Textarea
              value={agent.persona?.greeting || ""}
              onChange={(e) => updateAgent("persona.greeting", e.target.value)}
              placeholder="Hello! How may I assist you today?"
              rows={2}
            />
          </div>
          <div className="space-y-2">
            <Label>End Call Phrase</Label>
            <Textarea
              value={agent.conversation_settings?.end_phrase || ""}
              onChange={(e) => updateAgent("conversation_settings.end_phrase", e.target.value)}
              placeholder="Thank you for calling. Have a great day!"
              rows={2}
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>System Prompt</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={generatePrompt}
                disabled={isGeneratingPrompt}
                className="h-7"
              >
                {isGeneratingPrompt ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Sparkles className="h-3 w-3 mr-1" />
                )}
                AI Generate
              </Button>
            </div>
            <Textarea
              value={agent.persona?.system_prompt || ""}
              onChange={(e) => updateAgent("persona.system_prompt", e.target.value)}
              placeholder="You are a helpful AI voice assistant..."
              rows={6}
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Use variables like {"{{company_name}}"}, {"{{agent_name}}"}, {"{{business_hours}}"} for dynamic values.
            </p>
          </div>
          <div className="space-y-2">
            <Label>Personality Traits</Label>
            <div className="flex flex-wrap gap-2">
              {PERSONALITY_TRAITS.map((trait) => (
                <Button
                  key={trait}
                  type="button"
                  variant={selectedTraits.includes(trait) ? "default" : "outline"}
                  size="sm"
                  onClick={() => toggleTrait(trait)}
                  className="capitalize h-7 text-xs"
                >
                  {trait}
                </Button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 4. Conversation Settings ────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Conversation Settings</CardTitle>
          <CardDescription>Control call duration, interruptions, and silence handling</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2">
              <Label>Max Call Duration</Label>
              <Select
                value={String(agent.conversation_settings?.max_duration_seconds ?? 300)}
                onValueChange={(v) => updateAgent("conversation_settings.max_duration_seconds", parseInt(v))}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="120">2 minutes</SelectItem>
                  <SelectItem value="300">5 minutes</SelectItem>
                  <SelectItem value="600">10 minutes</SelectItem>
                  <SelectItem value="900">15 minutes</SelectItem>
                  <SelectItem value="1800">30 minutes</SelectItem>
                  <SelectItem value="3600">1 hour</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Interruption Handling</Label>
              <Select
                value={agent.conversation_settings?.interruption_handling ?? "barge_in"}
                onValueChange={(v) => updateAgent("conversation_settings.interruption_handling", v)}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="barge_in">Barge In — caller can interrupt</SelectItem>
                  <SelectItem value="wait">Wait — finish speaking first</SelectItem>
                  <SelectItem value="ignore">Ignore — caller must wait</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Silence Timeout</Label>
              <Select
                value={String(agent.conversation_settings?.silence_timeout_seconds ?? 10)}
                onValueChange={(v) => updateAgent("conversation_settings.silence_timeout_seconds", parseInt(v))}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="3">3 seconds</SelectItem>
                  <SelectItem value="5">5 seconds</SelectItem>
                  <SelectItem value="10">10 seconds</SelectItem>
                  <SelectItem value="15">15 seconds</SelectItem>
                  <SelectItem value="30">30 seconds</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Language</Label>
              <Select
                value={agent.conversation_settings?.language ?? "en"}
                onValueChange={(v) => updateAgent("conversation_settings.language", v)}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="es">Spanish</SelectItem>
                  <SelectItem value="fr">French</SelectItem>
                  <SelectItem value="de">German</SelectItem>
                  <SelectItem value="pt">Portuguese</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 5. Capabilities ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Capabilities</CardTitle>
          <CardDescription>Enable or disable specific agent features</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2">
            {[
              { key: "answer_calls", label: "Answer Calls", desc: "Receive and handle inbound calls" },
              { key: "make_calls", label: "Make Calls", desc: "Place outbound calls" },
              { key: "schedule_appointments", label: "Schedule Appointments", desc: "Book calendar appointments" },
              { key: "send_confirmations", label: "Send Confirmations", desc: "Send email/SMS confirmations" },
              { key: "take_messages", label: "Take Messages", desc: "Record and deliver messages" },
              { key: "transfer_calls", label: "Transfer Calls", desc: "Transfer to human agents" },
              { key: "qualify_leads", label: "Qualify Leads", desc: "Score and qualify leads" },
            ].map((cap) => (
              <div key={cap.key} className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <p className="text-sm font-medium">{cap.label}</p>
                  <p className="text-xs text-muted-foreground">{cap.desc}</p>
                </div>
                <Switch
                  checked={agent.capabilities?.[cap.key as keyof typeof agent.capabilities] || false}
                  onCheckedChange={(checked) => updateAgent(`capabilities.${cap.key}`, checked)}
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── 6. Transfer Rules ───────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Transfer Rules</CardTitle>
          <CardDescription>Define when and where calls should be forwarded to a human</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Switch
                checked={agent.transfer_settings?.enabled || false}
                onCheckedChange={(checked) => updateAgent("transfer_settings.enabled", checked)}
              />
              <Label className="text-sm">Enable call transfers</Label>
            </div>
          </div>

          {agent.transfer_settings?.enabled && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Default Transfer Number</Label>
                <Input
                  value={agent.transfer_settings?.default_number || ""}
                  onChange={(e) => updateAgent("transfer_settings.default_number", e.target.value)}
                  placeholder="+1 (555) 000-0000"
                />
                <p className="text-xs text-muted-foreground">
                  Fallback number when no specific rule matches
                </p>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Transfer Rules</Label>
                  <Button type="button" variant="outline" size="sm" className="h-7" onClick={addTransferRule}>
                    <Plus className="h-3 w-3 mr-1" /> Add Rule
                  </Button>
                </div>
                {(agent.transfer_settings?.rules || []).map((rule, idx) => (
                  <div key={idx} className="flex gap-2 items-end border rounded-lg p-3">
                    <div className="flex-1 space-y-1">
                      <Label className="text-xs">Condition</Label>
                      <Input
                        value={rule.condition}
                        onChange={(e) => updateTransferRule(idx, "condition", e.target.value)}
                        placeholder="e.g. urgent, angry, billing"
                        className="h-8 text-sm"
                      />
                    </div>
                    <div className="flex-1 space-y-1">
                      <Label className="text-xs">Transfer To</Label>
                      <Input
                        value={rule.destination}
                        onChange={(e) => updateTransferRule(idx, "destination", e.target.value)}
                        placeholder="+1 (555) 000-0000"
                        className="h-8 text-sm"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={rule.announce}
                        onCheckedChange={(checked) => updateTransferRule(idx, "announce", checked)}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                        onClick={() => removeTransferRule(idx)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
                {(agent.transfer_settings?.rules || []).length === 0 && (
                  <p className="text-xs text-muted-foreground italic">No rules yet. Add a rule to define transfer conditions.</p>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── 7. Analytics ────────────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Performance</CardTitle>
          <CardDescription>Agent statistics</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4">
            {[
              { label: "Total Calls", value: agent.analytics?.total_calls ?? 0 },
              { label: "Total Minutes", value: agent.analytics?.total_minutes ?? 0 },
              { label: "Appointments", value: agent.analytics?.appointments_booked ?? 0 },
              { label: "Satisfaction", value: agent.analytics?.satisfaction_avg?.toFixed(1) ?? "N/A" },
            ].map((stat) => (
              <div key={stat.label} className="text-center p-4 rounded-lg bg-secondary">
                <p className="text-2xl font-bold">{stat.value}</p>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── Save Footer ─────────────────────────────────────────────────────── */}
      <div className="flex justify-end gap-3 pb-8">
        <Button variant="outline" onClick={() => router.push("/dashboard/agents")}>Cancel</Button>
        <Button onClick={handleSave} disabled={isSaving} className="min-w-[140px]">
          {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Save Changes
        </Button>
      </div>
    </div>
  );
}
