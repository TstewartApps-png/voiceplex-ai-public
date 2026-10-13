"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Phone, Clock, CheckCircle, TrendingUp } from "lucide-react";
import api from "@/lib/api";

interface AnalyticsData {
  total_calls: number;
  total_minutes: number;
  appointments_booked: number;
  avg_satisfaction: number;
}

export default function AnalyticsPage() {
  const [analytics, setAnalytics] = useState<AnalyticsData>({
    total_calls: 0,
    total_minutes: 0,
    appointments_booked: 0,
    avg_satisfaction: 0,
  });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchAnalytics();
  }, []);

  const fetchAnalytics = async () => {
    try {
      const [agentsRes, callsRes] = await Promise.all([
        api.get("/agents"),
        api.get("/calls", { params: { limit: 100 } }),
      ]);

      const agents = Array.isArray(agentsRes.data) ? agentsRes.data : agentsRes.data.items || [];
      const calls = callsRes.data.items || [];

      const totalCalls = calls.length;
      const totalMinutes = calls.reduce(
        (sum: number, call: { duration_seconds?: number }) =>
          sum + Math.ceil((call.duration_seconds || 0) / 60),
        0
      );
      const appointmentsBooked = calls.filter(
        (call: { outcome?: string }) => call.outcome === "appointment_scheduled"
      ).length;

      const agentStats = agents.reduce(
        (sum: number, agent: { analytics: { satisfaction_avg: number } }) =>
          sum + (agent.analytics.satisfaction_avg || 0),
        0
      );
      const avgSatisfaction = agents.length > 0 ? agentStats / agents.length : 0;

      setAnalytics({
        total_calls: totalCalls,
        total_minutes: totalMinutes,
        appointments_booked: appointmentsBooked,
        avg_satisfaction: Math.round(avgSatisfaction * 100) / 100,
      });
    } catch (error) {
      console.error("Failed to fetch analytics:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const statCards = [
    {
      title: "Total Calls",
      value: analytics.total_calls,
      icon: Phone,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      title: "Total Minutes",
      value: analytics.total_minutes,
      icon: Clock,
      color: "text-green-600",
      bg: "bg-green-50",
    },
    {
      title: "Appointments Booked",
      value: analytics.appointments_booked,
      icon: CheckCircle,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
    {
      title: "Avg Satisfaction",
      value: analytics.avg_satisfaction.toFixed(1),
      icon: TrendingUp,
      color: "text-orange-600",
      bg: "bg-orange-50",
    },
  ];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading analytics...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Analytics</h1>
        <p className="text-muted-foreground mt-1">
          Track performance and insights for your AI agents
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <div className={`rounded-lg p-2 ${stat.bg}`}>
                <stat.icon className={`h-4 w-4 ${stat.color}`} />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Call Volume Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Chart visualization coming soon
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Top Performing Agents</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Agent performance data coming soon
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
