"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Building2, Plus, Phone, Loader2, Trash2, Edit, X } from "lucide-react";
import api from "@/lib/api";
import { Company, Agent } from "@/types";

interface CompanyFormData {
  name: string;
  industry: string;
  website: string;
}

const getInitialFormData = (): CompanyFormData => ({
  name: "",
  industry: "",
  website: "",
});

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editingCompanyId, setEditingCompanyId] = useState<string | null>(null);
  const [formData, setFormData] = useState<CompanyFormData>(getInitialFormData());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Attach-number state
  const [agents, setAgents] = useState<Agent[]>([]);
  const [attachCompanyId, setAttachCompanyId] = useState<string | null>(null);
  const [attachNumber, setAttachNumber] = useState("");
  const [attachAgentId, setAttachAgentId] = useState("");
  const [attachFriendly, setAttachFriendly] = useState("");
  const [attachError, setAttachError] = useState("");
  const [isAttaching, setIsAttaching] = useState(false);

  useEffect(() => {
    fetchCompanies();
    api
      .get("/agents")
      .then((r) => setAgents(Array.isArray(r.data) ? r.data : r.data.items || []))
      .catch(() => setAgents([]));
  }, []);

  const openAttach = (companyId: string) => {
    setAttachCompanyId(companyId);
    setAttachNumber("");
    setAttachAgentId("");
    setAttachFriendly("");
    setAttachError("");
  };

  const handleAttachNumber = async () => {
    if (!attachCompanyId) return;
    setIsAttaching(true);
    setAttachError("");
    try {
      await api.post(`/companies/${attachCompanyId}/phone-numbers`, {
        number: attachNumber.trim(),
        friendly_name: attachFriendly,
        agent_id: attachAgentId || null,
      });
      setAttachCompanyId(null);
      fetchCompanies();
    } catch (err: any) {
      const d = err.response?.data;
      setAttachError(d?.detail || (d?.errors ? d.errors.join(", ") : "Failed to attach number"));
    } finally {
      setIsAttaching(false);
    }
  };

  const handleDetachNumber = async (companyId: string, numberId: string) => {
    if (!confirm("Remove this number from the company? (It stays in your Twilio account.)")) return;
    try {
      await api.delete(`/companies/${companyId}/phone-numbers/${numberId}`);
      fetchCompanies();
    } catch (err) {
      console.error("Failed to detach number:", err);
    }
  };

  const fetchCompanies = async () => {
    try {
      const response = await api.get("/companies");
      const data = Array.isArray(response.data) ? response.data : response.data.items || [];
      setCompanies(data);
    } catch (error) {
      console.error("Failed to fetch companies:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const openCreateModal = () => {
    setFormData(getInitialFormData());
    setIsEditing(false);
    setEditingCompanyId(null);
    setError("");
    setShowModal(true);
  };

  const openEditModal = (company: Company) => {
    setFormData({
      name: company.name,
      industry: company.industry || "",
      website: company.website || "",
    });
    setIsEditing(true);
    setEditingCompanyId(company.id);
    setError("");
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setFormData(getInitialFormData());
    setError("");
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setError("Company name is required");
      return;
    }

    setIsSubmitting(true);
    setError("");

    try {
      if (isEditing && editingCompanyId) {
        await api.put(`/companies/${editingCompanyId}`, formData);
      } else {
        await api.post("/companies", formData);
      }
      await fetchCompanies();
      closeModal();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosError = err as { response?: { data?: { detail?: string | { detail?: string } } } };
        const detail = axiosError.response?.data?.detail;
        if (typeof detail === "string") {
          setError(detail);
        } else if (detail && typeof detail === "object" && "detail" in detail) {
          setError(detail.detail || "Failed to save company");
        } else {
          setError("Failed to save company");
        }
      } else {
        setError("Failed to save company");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (companyId: string) => {
    if (!confirm("Are you sure you want to delete this company? This will also delete all associated agents.")) {
      return;
    }

    try {
      await api.delete(`/companies/${companyId}`);
      await fetchCompanies();
    } catch (err) {
      console.error("Failed to delete company:", err);
      alert("Failed to delete company. Please try again.");
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading companies...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Companies</h1>
          <p className="text-muted-foreground mt-1">
            Manage your business locations and settings
          </p>
        </div>
        <Button onClick={openCreateModal}>
          <Plus className="mr-2 h-4 w-4" />
          Add Company
        </Button>
      </div>

      {companies.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No companies yet</CardTitle>
            <CardDescription>
              Create your first company to start using VoicePlex
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={openCreateModal}>
              <Plus className="mr-2 h-4 w-4" />
              Create Company
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {companies.map((company) => (
            <Card key={company.id}>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
                    <Building2 className="h-6 w-6 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <CardTitle className="truncate">{company.name}</CardTitle>
                    {company.industry && (
                      <p className="text-sm text-muted-foreground truncate">{company.industry}</p>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {company.website && (
                    <div>
                      <p className="text-xs text-muted-foreground">Website</p>
                      <p className="text-sm truncate">{company.website}</p>
                    </div>
                  )}
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Phone Numbers</p>
                    {company.phone_numbers.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No phone numbers</p>
                    ) : (
                      <div className="space-y-1">
                        {company.phone_numbers.map((phone) => {
                          const agent = agents.find((a) => a.id === phone.agent_id);
                          return (
                            <div key={phone.id} className="flex items-center gap-2 text-sm">
                              <Phone className="h-3 w-3" />
                              <span>{phone.number}</span>
                              <span className="text-xs text-muted-foreground truncate">
                                → {agent ? agent.name : "no agent"}
                              </span>
                              <button
                                className="ml-auto text-muted-foreground hover:text-destructive"
                                title="Detach number"
                                onClick={() => handleDetachNumber(company.id, phone.id)}
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                    <Button variant="ghost" size="sm" className="mt-2 px-2" onClick={() => openAttach(company.id)}>
                      <Plus className="mr-1 h-3 w-3" />
                      Attach Twilio number
                    </Button>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={() => openEditModal(company)}
                    >
                      <Edit className="mr-2 h-4 w-4" />
                      Manage
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => handleDelete(company.id)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Attach phone number modal */}
      <Dialog open={attachCompanyId !== null} onOpenChange={(open) => !open && setAttachCompanyId(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Phone className="h-5 w-5" />
              Attach Twilio number
            </DialogTitle>
            <DialogDescription>
              Use a number you already own in the Twilio account configured under Settings. Its voice
              webhook will be pointed at this backend and calls will be answered by the selected agent.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="attach-number">Phone number (E.164)</Label>
              <Input id="attach-number" placeholder="+14155552671" value={attachNumber} onChange={(e) => setAttachNumber(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="attach-agent">Agent</Label>
              <select
                id="attach-agent"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={attachAgentId}
                onChange={(e) => setAttachAgentId(e.target.value)}
              >
                <option value="">— none yet —</option>
                {agents
                  .filter((a) => a.company_id === attachCompanyId)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} {a.status !== "active" ? `(${a.status})` : ""}
                    </option>
                  ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="attach-friendly">Label (optional)</Label>
              <Input id="attach-friendly" placeholder="Front desk" value={attachFriendly} onChange={(e) => setAttachFriendly(e.target.value)} />
            </div>
            {attachError && <p className="text-sm text-destructive">{attachError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAttachCompanyId(null)}>Cancel</Button>
            <Button onClick={handleAttachNumber} disabled={isAttaching || !attachNumber.trim()}>
              {isAttaching ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Attach
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create/Edit Company Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              {isEditing ? "Edit Company" : "Add Company"}
            </DialogTitle>
            <DialogDescription>
              {isEditing ? "Update your company details." : "Create a new company to organize your agents."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="company-name">Company Name *</Label>
              <Input
                id="company-name"
                placeholder="Acme Corporation"
                value={formData.name}
                onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-industry">Industry</Label>
              <Input
                id="company-industry"
                placeholder="Technology, Healthcare, Retail..."
                value={formData.industry}
                onChange={(e) => setFormData(prev => ({ ...prev, industry: e.target.value }))}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="company-website">Website</Label>
              <Input
                id="company-website"
                placeholder="https://example.com"
                value={formData.website}
                onChange={(e) => setFormData(prev => ({ ...prev, website: e.target.value }))}
              />
            </div>

            {error && (
              <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive">
                {error}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeModal}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {isEditing ? "Saving..." : "Creating..."}
                </>
              ) : (
                isEditing ? "Save Changes" : "Create Company"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
