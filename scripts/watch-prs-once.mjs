#!/usr/bin/env node

import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const WATCH_DIR =
  process.env.PR_WATCH_DIR ||
  `${process.env.HOME || '.'}/.local/state/reputation-controller/pr-watch`;
const WATCHLIST_PATH = `${WATCH_DIR}/watchlist.json`;
const STATE_PATH = `${WATCH_DIR}/state.json`;
const LOG_PATH = `${WATCH_DIR}/events.jsonl`;
const DISABLED_PATH = `${WATCH_DIR}/DISABLED`;
const LABEL = 'com.reputation-controller.pr-watch';
const GH = process.env.GH_PATH || 'gh';

function readJson(path) {
  return JSON.parse(fs.readFileSync(path, 'utf8'));
}

function writeJson(path, value) {
  fs.writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

function appendEvent(event) {
  fs.mkdirSync(WATCH_DIR, { recursive: true });
  fs.appendFileSync(LOG_PATH, `${JSON.stringify(event)}\n`);
}

function now() {
  return new Date().toISOString();
}

function ghPrView(repo, number) {
  const result = spawnSync(
    GH,
    [
      'pr',
      'view',
      String(number),
      '--repo',
      repo,
      '--json',
      'url,title,state,mergedAt,reviewDecision,mergeStateStatus,isDraft,statusCheckRollup,commits,reviews,comments',
    ],
    { encoding: 'utf8' },
  );
  if (result.status !== 0) {
    return {
      ok: false,
      error: (result.stderr || result.stdout || 'gh pr view failed').trim(),
    };
  }
  return { ok: true, pr: JSON.parse(result.stdout) };
}

function summarizeChecks(rollup) {
  const checks = Array.isArray(rollup) ? rollup : [];
  const activeChecks = checks.filter((check) => check.conclusion !== 'SKIPPED');
  const pending = activeChecks.filter((check) => check.status !== 'COMPLETED');
  const failedChecks = activeChecks.filter((check) =>
    ['ACTION_REQUIRED', 'CANCELLED', 'FAILURE', 'STARTUP_FAILURE', 'TIMED_OUT'].includes(
      check.conclusion,
    ),
  );
  const externalBlocked = failedChecks.filter((check) =>
    ['authorize', 'Sourcery review'].includes(check.name),
  );
  const failed = failedChecks.filter(
    (check) => !externalBlocked.some((blocked) => blocked.name === check.name),
  );
  const passed =
    activeChecks.length > 0 &&
    pending.length === 0 &&
    failedChecks.length === 0 &&
    activeChecks.every((check) =>
      ['SUCCESS', 'NEUTRAL'].includes(check.conclusion),
    );
  return {
    total: checks.length,
    active: activeChecks.length,
    pending: pending.map((check) => check.name),
    failed: failed.map((check) => ({
      name: check.name,
      conclusion: check.conclusion,
      url: check.detailsUrl,
    })),
    external_blocked: externalBlocked.map((check) => ({
      name: check.name,
      conclusion: check.conclusion,
      url: check.detailsUrl,
    })),
    passed,
  };
}

function parseTimestamp(value) {
  if (typeof value !== 'string' || value.length === 0) {
    return null;
  }
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function latestTimestamp(items, field) {
  if (!Array.isArray(items)) {
    return null;
  }
  let latest = null;
  for (const item of items) {
    const timestamp = parseTimestamp(item?.[field]);
    if (timestamp !== null && (latest === null || timestamp > latest)) {
      latest = timestamp;
    }
  }
  return latest;
}

function latestChangesRequestedTimestamp(reviews) {
  if (!Array.isArray(reviews)) {
    return null;
  }
  return latestTimestamp(
    reviews.filter((review) => review?.state === 'CHANGES_REQUESTED'),
    'submittedAt',
  );
}

function authorLogin(item) {
  const author = item?.author;
  if (typeof author === 'string') {
    return author;
  }
  if (author && typeof author === 'object') {
    return String(author.login || '');
  }
  return '';
}

function isBotLogin(login) {
  const normalized = login.toLowerCase();
  return (
    normalized.endsWith('[bot]') ||
    normalized.includes('bot') ||
    normalized === 'copilot' ||
    normalized.startsWith('sourcery')
  );
}

function latestOwnCommentTimestamp(comments, actor) {
  if (!actor || !Array.isArray(comments)) {
    return null;
  }
  return latestTimestamp(
    comments.filter((comment) => authorLogin(comment) === actor),
    'createdAt',
  );
}

function requestLikeComment(body) {
  if (typeof body !== 'string') {
    return false;
  }
  return /\b(please|can you|address|screenshot|reproduc|fix|change)\b/i.test(body);
}

function latestActionableMaintainerComment(pr, actor, latestCommitAt) {
  const comments = Array.isArray(pr.comments) ? pr.comments : [];
  const latestOwnCommentAt = latestOwnCommentTimestamp(comments, actor);
  const threshold = Math.max(latestCommitAt || 0, latestOwnCommentAt || 0);
  let latest = null;
  for (const comment of comments) {
    const timestamp = parseTimestamp(comment?.createdAt);
    const login = authorLogin(comment);
    if (
      timestamp !== null &&
      timestamp > threshold &&
      login !== actor &&
      !isBotLogin(login) &&
      requestLikeComment(comment?.body)
    ) {
      if (latest === null || timestamp > latest.timestamp) {
        latest = {
          timestamp,
          author: login,
        };
      }
    }
  }
  return latest;
}

export function classify(pr, options = {}) {
  const checks = summarizeChecks(pr.statusCheckRollup);
  const closed = pr.state !== 'OPEN' || Boolean(pr.mergedAt);
  const closedUnmerged = pr.state !== 'OPEN' && !pr.mergedAt;
  const latestCommitAt = latestTimestamp(pr.commits, 'committedDate');
  const latestChangesRequestedAt = latestChangesRequestedTimestamp(pr.reviews);
  const addressedChangesRequest =
    latestCommitAt !== null &&
    latestChangesRequestedAt !== null &&
    latestCommitAt > latestChangesRequestedAt;
  const changesRequested =
    latestChangesRequestedAt !== null && !addressedChangesRequest;
  const actionableComment = latestActionableMaintainerComment(
    pr,
    options.actor || '',
    latestCommitAt,
  );
  const mergeBlockedByConflict = ['DIRTY', 'UNKNOWN'].includes(pr.mergeStateStatus);
  const needsAttention =
    !closed &&
    (checks.failed.length > 0 ||
      changesRequested ||
      Boolean(actionableComment) ||
      mergeBlockedByConflict);
  let attentionReason = null;
  if (!closed && checks.failed.length > 0) {
    attentionReason = 'checks_failed';
  } else if (!closed && changesRequested) {
    attentionReason = 'changes_requested_unaddressed';
  } else if (!closed && actionableComment) {
    attentionReason = 'maintainer_comment_after_author';
  } else if (!closed && mergeBlockedByConflict) {
    attentionReason = 'merge_blocked_by_conflict';
  }
  return {
    closed,
    closed_unmerged: closedUnmerged,
    needs_attention: needsAttention,
    attention_reason: attentionReason,
    waiting_review:
      !closed &&
      !needsAttention &&
      (pr.reviewDecision === 'REVIEW_REQUIRED' ||
        addressedChangesRequest ||
        checks.external_blocked.length > 0),
    latest_commit_at:
      latestCommitAt === null ? null : new Date(latestCommitAt).toISOString(),
    latest_changes_requested_at:
      latestChangesRequestedAt === null
        ? null
        : new Date(latestChangesRequestedAt).toISOString(),
    latest_actionable_comment_at:
      actionableComment === null
        ? null
        : new Date(actionableComment.timestamp).toISOString(),
    actionable_comment_author:
      actionableComment === null ? null : actionableComment.author,
    addressed_changes_request: addressedChangesRequest,
    checks,
  };
}

function disableIfNeeded(allDone, enabled) {
  if (!allDone || !enabled) {
    return;
  }
  fs.writeFileSync(DISABLED_PATH, `${now()} all watched PRs are closed or merged\n`);
  appendEvent({ at: now(), type: 'auto_disabled', reason: 'all_prs_done' });
  if (process.env.PR_WATCH_DRY_RUN === '1') {
    return;
  }
  spawnSync('launchctl', ['bootout', `gui/${process.getuid()}`, LABEL], {
    encoding: 'utf8',
  });
}

function main() {
  if (fs.existsSync(DISABLED_PATH)) {
    appendEvent({ at: now(), type: 'skipped', reason: 'disabled_marker_exists' });
    return;
  }
  const watchlist = readJson(WATCHLIST_PATH);
  const results = [];
  for (const item of watchlist.prs || []) {
    const response = ghPrView(item.repo, item.number);
    if (!response.ok) {
      results.push({
        ...item,
        ok: false,
        needs_attention: true,
        error: response.error,
      });
      continue;
    }
    const pr = response.pr;
    const classification = classify(pr, {
      actor: process.env.GITHUB_ACTOR || process.env.GH_ACTOR || 'operator',
    });
    results.push({
      ...item,
      ok: true,
      url: pr.url,
      title: pr.title,
      state: pr.state,
      merged_at: pr.mergedAt,
      review_decision: pr.reviewDecision,
      merge_state_status: pr.mergeStateStatus,
      is_draft: pr.isDraft,
      ...classification,
    });
  }
  const allDone = results.length > 0 && results.every((item) => item.closed);
  const state = {
    checked_at: now(),
    all_done: allDone,
    open_count: results.filter((item) => !item.closed).length,
    needs_attention_count: results.filter((item) => item.needs_attention).length,
    results,
  };
  writeJson(STATE_PATH, state);
  appendEvent({ at: now(), type: 'check', state });
  disableIfNeeded(
    allDone,
    watchlist.disable_when_all_closed_or_merged !== false,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
