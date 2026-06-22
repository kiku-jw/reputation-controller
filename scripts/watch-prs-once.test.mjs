import assert from 'node:assert/strict';
import test from 'node:test';

import { classify } from './watch-prs-once.mjs';

function basePr(overrides = {}) {
  return {
    state: 'OPEN',
    mergedAt: null,
    reviewDecision: '',
    mergeStateStatus: 'CLEAN',
    statusCheckRollup: [
      { name: 'ci', status: 'COMPLETED', conclusion: 'SUCCESS' },
    ],
    commits: [
      { committedDate: '2026-06-13T18:25:50Z' },
    ],
    reviews: [],
    comments: [],
    ...overrides,
  };
}

test('classify flags unaddressed changes-requested review even when reviewDecision is empty', () => {
  const result = classify(
    basePr({
      reviewDecision: '',
      reviews: [
        {
          state: 'CHANGES_REQUESTED',
          submittedAt: '2026-06-16T10:29:55Z',
          author: { login: 'maintainer' },
        },
      ],
    }),
    { actor: 'kiku-jw' },
  );

  assert.equal(result.needs_attention, true);
  assert.equal(result.attention_reason, 'changes_requested_unaddressed');
  assert.equal(result.waiting_review, false);
});

test('classify flags request-like maintainer comment after author activity', () => {
  const result = classify(
    basePr({
      comments: [
        {
          author: { login: 'kiku-jw' },
          createdAt: '2026-06-15T15:30:50Z',
          body: 'Addressed the target blank feedback.',
        },
        {
          author: { login: 'maintainer' },
          createdAt: '2026-06-16T15:42:00Z',
          body: 'Please add screenshot of the UI where changed',
        },
      ],
    }),
    { actor: 'kiku-jw' },
  );

  assert.equal(result.needs_attention, true);
  assert.equal(result.attention_reason, 'maintainer_comment_after_author');
  assert.equal(result.latest_actionable_comment_at, '2026-06-16T15:42:00.000Z');
});

test('classify records closed unmerged PR outcome', () => {
  const result = classify(
    basePr({
      state: 'CLOSED',
      mergedAt: null,
    }),
    { actor: 'kiku-jw' },
  );

  assert.equal(result.closed, true);
  assert.equal(result.closed_unmerged, true);
  assert.equal(result.needs_attention, false);
});
