// Graxia Tool — API Load Test
// Tests 100 RPS for 5 minutes against the agent_list endpoint.
// Run: k6 run tests/load/api_load.js
//
// Prereq: API running at http://localhost:8000
// Optional: docker compose up -d

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const agentListDuration = new Trend('agent_list_duration');
const skillsListDuration = new Trend('skills_list_duration');
const systemStatusDuration = new Trend('system_status_duration');

export const options = {
  stages: [
    { duration: '30s', target: 50 },   // ramp up to 50 RPS
    { duration: '1m', target: 100 },   // ramp to 100 RPS
    { duration: '5m', target: 100 },   // sustain 100 RPS for 5 min
    { duration: '30s', target: 0 },    // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95% of requests < 500ms
    http_req_failed: ['rate<0.01'],    // error rate < 1%
    errors: ['rate<0.05'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  // Test 1: agent_list endpoint
  const agentRes = http.get(`${BASE_URL}/api/agents`, {
    headers: { 'Content-Type': 'application/json' },
  });

  const agentOk = check(agentRes, {
    'agent_list status 200': (r) => r.status === 200,
    'agent_list has body': (r) => r.body && r.body.length > 0,
    'agent_list < 200ms': (r) => r.timings.duration < 200,
  });

  errorRate.add(!agentOk);
  agentListDuration.add(agentRes.timings.duration);

  sleep(0.01);  // small delay between requests

  // Test 2: skills_list endpoint
  const skillsRes = http.get(`${BASE_URL}/api/skills`, {
    headers: { 'Content-Type': 'application/json' },
  });

  const skillsOk = check(skillsRes, {
    'skills_list status 200': (r) => r.status === 200,
  });

  errorRate.add(!skillsOk);
  skillsListDuration.add(skillsRes.timings.duration);

  sleep(0.01);

  // Test 3: system_status endpoint
  const statusRes = http.get(`${BASE_URL}/api/status`, {
    headers: { 'Content-Type': 'application/json' },
  });

  const statusOk = check(statusRes, {
    'system_status status 200': (r) => r.status === 200,
    'system_status operational': (r) => {
      try {
        return JSON.parse(r.body).status === 'operational';
      } catch {
        return false;
      }
    },
  });

  errorRate.add(!statusOk);
  systemStatusDuration.add(statusRes.timings.duration);

  sleep(0.01);
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'tests/load/results.json': JSON.stringify(data, null, 2),
  };
}

function textSummary(data, opts) {
  // Simple text summary
  const indent = opts.indent || '';
  let out = `\n${indent}=== LOAD TEST RESULTS ===\n\n`;
  out += `${indent}Total requests: ${data.metrics.http_reqs.values.count}\n`;
  out += `${indent}Request rate: ${data.metrics.http_reqs.values.rate.toFixed(2)}/s\n`;
  out += `${indent}p95 latency: ${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms\n`;
  out += `${indent}p99 latency: ${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms\n`;
  out += `${indent}Failed requests: ${(data.metrics.http_req_failed.values.rate * 100).toFixed(2)}%\n`;
  out += `${indent}Error rate: ${(data.metrics.errors.values.rate * 100).toFixed(2)}%\n\n`;

  if (data.metrics.agent_list_duration) {
    out += `${indent}agent_list avg: ${data.metrics.agent_list_duration.values.avg.toFixed(2)}ms\n`;
  }
  if (data.metrics.skills_list_duration) {
    out += `${indent}skills_list avg: ${data.metrics.skills_list_duration.values.avg.toFixed(2)}ms\n`;
  }
  if (data.metrics.system_status_duration) {
    out += `${indent}system_status avg: ${data.metrics.system_status_duration.values.avg.toFixed(2)}ms\n`;
  }

  return out;
}
