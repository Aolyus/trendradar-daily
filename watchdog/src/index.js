const SLOT_BY_CRON = {
  "17 3 * * *": "morning",
  "17 8 * * *": "afternoon",
};

function required(env, name) {
  const value = env[name]?.trim();
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

export async function dispatchWorkflow(env, slot, fetchImpl = fetch) {
  if (!new Set(["morning", "afternoon"]).has(slot)) {
    throw new Error(`Unsupported delivery slot: ${slot}`);
  }

  const owner = required(env, "GITHUB_OWNER");
  const repo = required(env, "GITHUB_REPO");
  const workflow = required(env, "GITHUB_WORKFLOW");
  const ref = required(env, "GITHUB_REF");
  const token = required(env, "GITHUB_TOKEN");
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "trendradar-cloudflare-watchdog",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({
      ref,
      inputs: {
        slot,
        source: "watchdog",
        force: "false",
        dry_run: "false",
      },
    }),
  });

  if (!response.ok) {
    const detail = (await response.text()).slice(0, 1000);
    throw new Error(`GitHub dispatch failed (${response.status}): ${detail}`);
  }

  console.log(JSON.stringify({ event: "workflow_dispatched", slot, status: response.status }));
}

export default {
  async scheduled(controller, env, ctx) {
    const slot = SLOT_BY_CRON[controller.cron];
    if (!slot) throw new Error(`Unknown watchdog cron: ${controller.cron}`);
    ctx.waitUntil(dispatchWorkflow(env, slot));
  },

  async fetch() {
    return Response.json({ service: "trendradar-watchdog", status: "ok" });
  },
};
