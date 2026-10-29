/**
 * First sync must survive being killed mid-pagination.
 *
 * A real account can have hundreds of conversations; fetching and pushing
 * all of them in one shot easily exceeds how long Chrome lets an MV3 service
 * worker run continuously, and the old code only checkpointed progress once
 * at the very end — a kill mid-sync meant every retry restarted from zero
 * and hit the same wall again, forever (see the "first sync never completes
 * on large accounts" bug this fixes).
 *
 * These tests drive two conversation-list pages through a custom router that
 * can be made to fail on page 2, to prove: page 1's messages are pushed and
 * checkpointed independently of page 2's outcome, a resumed run picks up
 * from the checkpoint instead of re-fetching/re-pushing page 1, and the real
 * watermark is only set once pagination genuinely finishes.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeChrome } from "./helpers/chrome-stub.mjs";
import { makeFakeBackend } from "./helpers/fake-backend.mjs";
import { loadModules, SYNC_FILES } from "./helpers/loader.mjs";

const FIXED_NOW = 1750000000000;
const LINKEDIN_COOKIES = [
  { name: "li_at", value: "li-at-stub", domain: ".linkedin.com" },
  { name: "JSESSIONID", value: '"ajax:1234"', domain: ".linkedin.com" },
];

const ME_FIXTURE = { data: { entityUrn: "urn:li:fsd_profile:SELF123" } };

function conversationFixture(id, lastActivityAt, firstName) {
  return {
    entityUrn: `urn:li:msg_conversation:${id}`,
    backendUrn: `urn:li:msg_conversation:${id}`,
    lastActivityAt,
    title: { text: `${firstName} Partner` },
    conversationUrl: { url: `https://www.linkedin.com/messaging/thread/${id}` },
    conversationParticipants: [
      {
        hostIdentityUrn: `urn:li:fsd_profile:${id}_PARTNER`,
        participantType: { member: { profileUrl: `https://www.linkedin.com/in/${id}`, firstName, lastName: "Partner" } },
      },
      {
        hostIdentityUrn: "urn:li:fsd_profile:SELF123",
        participantType: { member: { profileUrl: "https://www.linkedin.com/in/self-user", firstName: "Self", lastName: "User" } },
      },
    ],
    messages: { elements: [] },
  };
}

function messagesFixture(id, createdAt) {
  return {
    data: {
      messengerMessagesByConversation: {
        elements: [
          {
            entityUrn: `urn:li:msg_message:${id}-M1`,
            createdAt,
            deliveredAt: createdAt,
            body: { text: `Message from ${id}` },
            sender: { hostIdentityUrn: `urn:li:fsd_profile:${id}_PARTNER` },
          },
        ],
      },
    },
  };
}

// Page 1: two recent conversations. Page 2: one older conversation, only
// returned once `failPage2` is false — otherwise the page-2 fetch throws,
// simulating the service worker dying partway through pagination.
function makeTwoPageRouter({ failPage2 = false } = {}) {
  const page1 = [
    conversationFixture("CONVA", FIXED_NOW - 1_000_000, "Alice"),
    conversationFixture("CONVB", FIXED_NOW - 2_000_000, "Bob"),
  ];
  const page2 = [conversationFixture("CONVC", FIXED_NOW - 3_000_000, "Carol")];

  return async (args) => {
    if (args.length === 2 && typeof args[1] === "number") {
      return { ok: true, dataUrl: "data:image/jpeg;base64,/9j/stub", via: "stub" };
    }
    const url = String(args[0] ?? "");

    if (url.includes("/voyager/api/me")) return { ok: true, status: 200, data: ME_FIXTURE };

    if (url.includes("voyagerMessagingGraphQL")) {
      const rawVars = url.split("variables=")[1] ?? "";
      const variables = decodeURIComponent(rawVars);

      if (url.includes("messengerConversations")) {
        if (!variables.includes("lastUpdatedBefore")) {
          return { ok: true, status: 200, data: { data: { messengerConversationsBySyncToken: { elements: page1 } } } };
        }
        if (failPage2) {
          throw new Error("RATE_LIMITED");
        }
        // Any cursor past page 1 returns page 2, then an empty page to stop.
        if (variables.includes(`lastUpdatedBefore:${FIXED_NOW - 2_000_000}`)) {
          return { ok: true, status: 200, data: { data: { messengerConversationsBySyncToken: { elements: page2 } } } };
        }
        return { ok: true, status: 200, data: { data: { messengerConversationsBySyncToken: { elements: [] } } } };
      }

      if (url.includes("messengerMessages")) {
        const convUrn = variables.match(/conversationUrn:([^,)]+)/)?.[1] ?? "";
        if (convUrn.includes("CONVA")) return { ok: true, status: 200, data: messagesFixture("CONVA", FIXED_NOW - 900_000) };
        if (convUrn.includes("CONVB")) return { ok: true, status: 200, data: messagesFixture("CONVB", FIXED_NOW - 1_900_000) };
        if (convUrn.includes("CONVC")) return { ok: true, status: 200, data: messagesFixture("CONVC", FIXED_NOW - 2_900_000) };
        return { ok: true, status: 200, data: { data: { messengerMessagesByConversation: { elements: [] } } } };
      }
    }

    return { ok: false, status: 404, body: "NO_FIXTURE: " + url };
  };
}

function harness({ seed = {}, failPage2 = false } = {}) {
  const fake = makeFakeBackend({});
  const stub = makeChrome({ executeScript: makeTwoPageRouter({ failPage2 }), cookies: LINKEDIN_COOKIES });
  for (const [k, v] of Object.entries(seed)) stub.store.set(k, v);
  const api = loadModules({
    chrome: stub.chrome,
    fetchImpl: fake.fetchImpl,
    files: SYNC_FILES,
    fixedNow: FIXED_NOW,
    exports: ["runSync"],
  });
  return { ...stub, ...fake, api };
}

test("page 1 is pushed and checkpointed even when page 2 fails", async () => {
  const h = harness({ seed: { apiUrl: "http://x", token: "t" }, failPage2: true });

  const result = await h.api.runSync("http://x", "t", true);

  // The RATE_LIMITED throw on page 2 surfaces as the sync's error...
  assert.equal(result.error, "RATE_LIMITED");

  // ...but page 1's two conversations were already pushed before that happened.
  assert.equal(h.pushes().length, 1, "page 1 was pushed before page 2 was attempted");
  assert.equal(h.pushes()[0].body.messages.length, 2, "both page-1 messages were in that push");

  // Progress survives: a resume checkpoint exists, pointing at page 1's
  // oldest conversation (the correct cursor for continuing pagination).
  assert.equal(h.store.get("firstSyncCursor"), FIXED_NOW - 2_000_000);

  // Critically, the real watermark is NOT set — isFirstSync must stay true
  // on the next attempt, or the delta-sync path would silently skip CONVC.
  assert.equal(h.store.get("watermark"), undefined, "watermark must not be set until pagination truly finishes");
});

test("a resumed sync continues from the checkpoint instead of restarting", async () => {
  // Seed storage as if the previous test's partial run already happened.
  const h = harness({
    seed: { apiUrl: "http://x", token: "t", firstSyncCursor: FIXED_NOW - 2_000_000 },
    failPage2: false,
  });

  const result = await h.api.runSync("http://x", "t", true);

  assert.equal(result.error, null);

  // Only page 2 (CONVC) should have been fetched and pushed this run — page
  // 1's conversations must not be re-processed.
  assert.equal(h.pushes().length, 1, "exactly one push: page 2 only");
  const pushedIds = h.pushes()[0].body.messages.map((m) => m.conversation_id);
  assert.ok(pushedIds.every((id) => id.includes("CONVC")), "only CONVC's message was pushed on resume");
  assert.equal(result.conversations, 1);
  assert.equal(result.messages, 1);

  // Pagination reached its natural end (empty page) — first sync is now
  // genuinely complete: watermark is set, and the checkpoint is cleared.
  assert.ok(h.store.get("watermark"), "watermark set once pagination finishes");
  assert.equal(h.store.get("firstSyncCursor"), undefined, "checkpoint cleared on completion");
});

test("a full, uninterrupted first sync across two pages pushes every conversation exactly once", async () => {
  const h = harness({ seed: { apiUrl: "http://x", token: "t" }, failPage2: false });

  const result = await h.api.runSync("http://x", "t", true);

  assert.equal(result.error, null);
  assert.equal(result.conversations, 3, "CONVA + CONVB + CONVC across both pages");
  assert.equal(result.messages, 3);

  // Pushed in two batches (one per page), not one giant push at the end.
  assert.equal(h.pushes().length, 2);
  const allPushedIds = h.pushes().flatMap((p) => p.body.messages.map((m) => m.conversation_id));
  assert.equal(allPushedIds.length, 3, "exactly one message per conversation, no duplicates across pages");
  assert.ok(allPushedIds.some((id) => id.includes("CONVA")));
  assert.ok(allPushedIds.some((id) => id.includes("CONVB")));
  assert.ok(allPushedIds.some((id) => id.includes("CONVC")));

  assert.ok(h.store.get("watermark"));
  assert.equal(h.store.get("firstSyncCursor"), undefined);
});
