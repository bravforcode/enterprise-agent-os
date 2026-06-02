// Graxia Tool — Stress Test
// Pushes system to 200 RPS to find breaking point.
// Run: k6 run tests/load/stress_test.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');

export const options = {
  stages: [
    { duration: '30s', target: 100 },   // ramp to 100
    { duration: '30s', target: 200 },   // ramp to 200
    { duration: '1m', target: 200 },    // sustain 200 RPS
    { duration: '30s', target: 300 },   // push to 300
    { duration: '30s', target: 0 },     // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'],  // 95% under 1s
    http_req_failed: ['rate<0.05'],     // error rate < 5%
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  // Random endpoint selection
  const endpoints = [
    '/api/agents',
    '/api/skills',
    '/api/status',
    '/api/cost',
  ];

  const path = endpoints[Math.floor(Math.random() * endpoints.length)];
  const res = http.get(`${BASE_URL}${path}`);

  const ok = check(res, {
    'status 200': (r) => r.status === 200,
  });

  errorRate.add(!ok);
  sleep(0.005);  // tight loop
}
