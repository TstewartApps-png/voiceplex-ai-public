"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Bot, Phone, Clock, TrendingUp } from "lucide-react";
import api from "@/lib/api";

interface DashboardStats {
  total_agents: number;
  active_agents: number;
  total_calls_today: number;
  total_calls_this_month: number;
  total_minutes_this_month: number;
  minutes_remaining: number;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const [agentsRes, callsRes, usageRes] = await Promise.all([
          api.get("/agents"),
          api.get("/calls", { params: { limit: 100 } }),
          api.get("/billing/usage"),
        ]);

        const agents = agentsRes.data;
        const calls = callsRes.data.items || [];
        const usage = usageRes.data;

        const today = new Date().toISOString().split("T")[0];
        const callsToday = calls.filter((call: { initiated_at: string }) =>
          call.initiated_at.startsWith(today)
        );

        setStats({
          total_agents: agents.length,
          active_agents: agents.filter((a: { status: string }) => a.status === "active").length,
          total_calls_today: callsToday.length,
          total_calls_this_month: calls.length,
          total_minutes_this_month: usage.minutes_used,
          minutes_remaining: usage.minutes_included - usage.minutes_used,
        });
      } catch (error) {
        console.error("Failed to fetch dashboard stats:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchStats();
  }, []);

  const statCards = [
    {
      title: "Active Agents",
      value: stats?.active_agents ?? 0,
      total: stats?.total_agents ?? 0,
      icon: Bot,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      title: "Calls Today",
      value: stats?.total_calls_today ?? 0,
      icon: Phone,
      color: "text-green-600",
      bg: "bg-green-50",
    },
    {
      title: "Minutes Used",
      value: stats?.total_minutes_this_month ?? 0,
      icon: Clock,
      color: "text-orange-600",
      bg: "bg-orange-50",
    },
    {
      title: "Minutes Remaining",
      value: stats?.minutes_remaining ?? 0,
      icon: TrendingUp,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground mt-1">
          Overview of your VoicePlex AI platform
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
              <div className="text-2xl font-bold">
                {isLoading ? "..." : stat.value}
                {stat.total !== undefined && ` / ${stat.total}`}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              No recent activity to display
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Create your first agent to get started
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
