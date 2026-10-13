"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Check } from "lucide-react";
import api from "@/lib/api";
import { UsageStats, Plan } from "@/types";
import { useAuthStore } from "@/stores/authStore";

export default function BillingPage() {
  const { user } = useAuthStore();
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchBillingData();
  }, []);

  const fetchBillingData = async () => {
    try {
      const [usageRes, plansRes] = await Promise.all([
        api.get("/billing/usage"),
        api.get("/billing/plans"),
      ]);
      setUsage(usageRes.data);
      setPlans(plansRes.data);
    } catch (error) {
      console.error("Failed to fetch billing data:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleUpgrade = async (planId: string) => {
    try {
      const response = await api.post("/billing/subscribe", { plan: planId });
      if (response.data.checkout_url) {
        window.location.href = response.data.checkout_url;
      }
    } catch (error) {
      console.error("Failed to upgrade plan:", error);
    }
  };

  const currentPlan = user?.subscription?.plan || "free";
  const usagePercent = usage
    ? Math.round((usage.minutes_used / usage.minutes_included) * 100)
    : 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading billing information...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Billing & Subscription</h1>
        <p className="text-muted-foreground mt-1">
          Manage your subscription and view usage
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Current Plan</CardTitle>
            <CardDescription>
              You are currently on the {currentPlan} plan
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Plan</span>
                <Badge className="capitalize">{currentPlan}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Status</span>
                <Badge variant={user?.subscription?.status === "active" ? "default" : "secondary"}>
                  {user?.subscription?.status || "N/A"}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Usage This Month</CardTitle>
            <CardDescription>
              {usage?.minutes_used || 0} of {usage?.minutes_included || 0} minutes used
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="w-full bg-secondary rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all"
                  style={{ width: `${Math.min(usagePercent, 100)}%` }}
                />
              </div>
              <p className="text-sm text-muted-foreground">
                {usage?.minutes_included && usage.minutes_used > usage.minutes_included
                  ? `${usage.minutes_used - usage.minutes_included} overage minutes`
                  : `${usage?.minutes_included ? usage.minutes_included - usage.minutes_used : 0} minutes remaining`}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="text-2xl font-bold mb-4">Available Plans</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan) => (
            <Card key={plan.id} className={plan.id === currentPlan ? "border-primary" : ""}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span className="capitalize">{plan.name}</span>
                  {plan.id === currentPlan && (
                    <Badge variant="default">Current</Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  <span className="text-3xl font-bold">
                    ${plan.price_monthly}
                  </span>
                  /month
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <ul className="space-y-2 text-sm">
                  <li className="flex items-start gap-2">
                    <Check className="h-4 w-4 text-primary mt-0.5" />
                    <span>{plan.minutes_included} minutes/month</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-4 w-4 text-primary mt-0.5" />
                    <span>
                      {plan.max_agents === "unlimited" ? "Unlimited" : plan.max_agents} agents
                    </span>
                  </li>
                  {plan.features.map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <Check className="h-4 w-4 text-primary mt-0.5" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                {plan.id !== currentPlan && (
                  <Button
                    className="w-full"
                    onClick={() => handleUpgrade(plan.id)}
                  >
                    {plan.price_monthly === 0 ? "Downgrade" : "Upgrade"}
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
