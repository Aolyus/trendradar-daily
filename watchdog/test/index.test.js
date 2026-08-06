import assert from "node:assert/strict";
import test from "node:test";

import { dispatchWorkflow } from "../src/index.js";

const env = {
  GITHUB_OWNER: "Aolyus",
  GITHUB_REPO: "trendradar-daily",
  GITHUB_WORKFLOW: "crawler.yml",
  GITHUB_REF: "main",
  GITHUB_TOKEN: "test-token",
};

test("dispatches the requested slot without forcing a duplicate", async () => {
  let request;
  const fakeFetch = async (url, options) => {
    request = { url, options };
    return new Response(null, { status: 204 });
  };

  await dispatchWorkflow(env, "morning", fakeFetch);
  const body = JSON.parse(request.options.body);
  assert.match(request.url, /actions\/workflows\/crawler\.yml\/dispatches$/);
  assert.equal(body.inputs.slot, "morning");
  assert.equal(body.inputs.source, "watchdog");
  assert.equal(body.inputs.force, "false");
});

test("fails loudly when GitHub rejects the dispatch", async () => {
  const fakeFetch = async () => new Response("denied", { status: 403 });
  await assert.rejects(
    dispatchWorkflow(env, "afternoon", fakeFetch),
    /GitHub dispatch failed \(403\): denied/,
  );
});
