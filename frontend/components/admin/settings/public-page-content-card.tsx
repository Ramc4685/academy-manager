"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminPublicPageSettings,
  listAdminUsers,
  updateAdminPublicPageSettings,
  uploadAdminAcademyPhoto,
} from "@/lib/api/admin";
import {
  ABOUT_MAX,
  BIO_MAX,
  CAPTION_MAX,
  FAQS_MAX,
  FAQ_ANSWER_MAX,
  FAQ_QUESTION_MAX,
  GALLERY_CONSENT_LABEL,
  GALLERY_MAX,
  HIGHLIGHTS_MAX,
  HIGHLIGHT_MAX_CHARS,
  addHighlight,
  coachRows,
  contentErrors,
  contentPayload,
  galleryUploadBlocker,
  isCoachShown,
  moveItem,
  setCoachProfile,
  toContentForm,
  type ContentForm,
} from "@/lib/public-page/content-settings";
import { queryKeys } from "@/lib/query/keys";
import { Button, Card, Overline } from "@/components/ds";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";
import { PhotoUpload } from "@/components/admin/settings/photo-upload";

const INPUT_CLASS =
  "min-h-11 w-full rounded-md border border-rally-line bg-white px-3 text-sm text-rally-ink";
const TEXTAREA_CLASS =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink";
const LINK_BUTTON_CLASS =
  "inline-flex min-h-9 items-center rounded-md px-2 text-xs font-semibold text-rally-cobalt-700 underline-offset-2 hover:underline disabled:opacity-40 disabled:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rally-cobalt-600";

const uploadHero = (file: File) => uploadAdminAcademyPhoto(file, "hero");
const uploadCoach = (file: File) => uploadAdminAcademyPhoto(file, "coach");
const uploadGallery = (file: File) => uploadAdminAcademyPhoto(file, "gallery", { consent: true });

/**
 * Settings > Public page > Photos & details (Settings overhaul Phase 6).
 *
 * The owner and admins edit the landing page's hero photo, About us text,
 * highlights, gallery, coach profiles and FAQs here. Everything is one draft
 * saved with one button and guarded by the settings unsaved-changes guard;
 * uploads only fetch a URL, exactly like the logo. Leaving a section empty
 * keeps today's page.
 */
export function PublicPageContentCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.publicPage(),
    queryFn: getAdminPublicPageSettings,
  });
  const coachQuery = useQuery({
    queryKey: queryKeys.admin.users("coaches"),
    queryFn: () => listAdminUsers(undefined, { roles: ["coach", "assistant_coach"] }),
  });
  const original = useMemo(() => toContentForm(query.data), [query.data]);
  // `null` = untouched: the form follows the server copy, so a late load or a
  // background refetch never wipes edits (a touched draft stays as typed).
  const [draft, setDraft] = useState<ContentForm | null>(null);
  const form = draft ?? original;
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [newHighlight, setNewHighlight] = useState("");

  const coachUsers = coachQuery.data?.users ?? null;
  const coaches = useMemo(
    () => coachRows(coachUsers ?? [], form.coach_profiles),
    [coachUsers, form.coach_profiles],
  );
  // Until the coach list loads, do not drop any saved profile from a Save.
  const knownCoachIds = useMemo(
    () => (coachUsers ? new Set(coachUsers.map((user) => user.user_id)) : null),
    [coachUsers],
  );

  const payload = contentPayload(original, form, knownCoachIds);
  const errors = contentErrors(form);
  const dirty = Object.keys(payload).length > 0;
  useReportSettingsDirty("public-page-content", dirty);

  function edit(change: Partial<ContentForm>) {
    setDraft({ ...form, ...change });
  }

  /** For async callbacks (an upload finishing): build from the latest draft. */
  function editWith(change: (current: ContentForm) => Partial<ContentForm>) {
    setDraft((previous) => {
      const current = previous ?? original;
      return { ...current, ...change(current) };
    });
  }

  const mutation = useMutation({
    mutationFn: () => updateAdminPublicPageSettings(payload),
    onSuccess: (data) => {
      setSavedAt(savedAtNow());
      setDraft(null);
      queryClient.setQueryData(queryKeys.admin.publicPage(), data);
    },
  });

  const blocker = galleryUploadBlocker({ consent, count: form.gallery.length });

  return (
    <Card p={24} className="max-w-3xl" data-testid="public-page-content-card">
      <Overline>Photos &amp; details</Overline>
      <p className="mt-1 text-sm text-rally-muted">
        What families see first on your page. Leave a section empty to keep the standard page.
      </p>

      {/* Hero photo */}
      <section className="mt-5 grid gap-2" aria-labelledby="public-page-hero-heading">
        <h3 id="public-page-hero-heading" className="text-sm font-semibold text-rally-ink">
          Hero photo
        </h3>
        {form.hero_photo_url && (
          <div className="flex flex-wrap items-center gap-3">
            <div className="h-24 w-40 overflow-hidden rounded-md border border-rally-line bg-rally-paper">
              <img
                src={form.hero_photo_url}
                alt="Hero photo preview"
                data-testid="public-page-hero-preview"
                className="h-full w-full object-cover"
              />
            </div>
            <button
              type="button"
              data-testid="public-page-hero-remove"
              className={LINK_BUTTON_CLASS}
              onClick={() => edit({ hero_photo_url: null })}
            >
              Remove photo
            </button>
          </div>
        )}
        <PhotoUpload
          testId="public-page-hero-upload"
          label="Hero photo"
          buttonLabel={form.hero_photo_url ? "Replace photo" : "Upload photo"}
          hint="A wide photo of your court or class. PNG or JPG, up to 5 MB."
          upload={uploadHero}
          onUploaded={(url) => editWith(() => ({ hero_photo_url: url }))}
        />
      </section>

      {/* About us */}
      <div className="mt-6 grid gap-1">
        <label htmlFor="public-page-about" className="text-sm font-semibold text-rally-ink">
          About us
        </label>
        <textarea
          id="public-page-about"
          data-testid="public-page-about"
          rows={5}
          maxLength={ABOUT_MAX}
          value={form.about_text}
          onChange={(event) => edit({ about_text: event.target.value })}
          placeholder="Est. 2019. Who you are and who your classes are for."
          className={TEXTAREA_CLASS}
        />
        <span className="text-xs text-rally-subtle" data-testid="public-page-about-count">
          {form.about_text.length} / {ABOUT_MAX}
        </span>
      </div>

      {/* Highlights */}
      <section className="mt-6 grid gap-2" aria-labelledby="public-page-highlights-heading">
        <h3 id="public-page-highlights-heading" className="text-sm font-semibold text-rally-ink">
          Highlights
        </h3>
        {form.highlights.length > 0 && (
          <ul className="flex flex-wrap gap-2" data-testid="public-page-highlights">
            {form.highlights.map((item, index) => (
              <li
                key={`${item}-${index}`}
                className="inline-flex items-center gap-1 rounded-full border border-rally-line bg-rally-paper py-1 pl-3 pr-1 text-sm text-rally-ink"
              >
                {item}
                <button
                  type="button"
                  aria-label={`Remove highlight ${item}`}
                  data-testid="public-page-highlight-remove"
                  className="inline-flex size-7 items-center justify-center rounded-full text-rally-muted hover:bg-white"
                  onClick={() =>
                    edit({ highlights: form.highlights.filter((_, i) => i !== index) })
                  }
                >
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {form.highlights.length < HIGHLIGHTS_MAX ? (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              edit({ highlights: addHighlight(form.highlights, newHighlight) });
              setNewHighlight("");
            }}
          >
            <label htmlFor="public-page-highlight-input" className="sr-only">
              New highlight
            </label>
            <input
              id="public-page-highlight-input"
              data-testid="public-page-highlight-input"
              value={newHighlight}
              maxLength={HIGHLIGHT_MAX_CHARS}
              onChange={(event) => setNewHighlight(event.target.value)}
              placeholder="Small groups"
              className={`${INPUT_CLASS} max-w-xs`}
            />
            <Button
              type="submit"
              variant="secondary"
              size="sm"
              disabled={!newHighlight.trim()}
              data-testid="public-page-highlight-add"
            >
              Add highlight
            </Button>
          </form>
        ) : (
          <p className="text-xs text-rally-subtle">
            You have {HIGHLIGHTS_MAX} highlights, the most the page shows.
          </p>
        )}
      </section>

      {/* Gallery */}
      <section className="mt-6 grid gap-3" aria-labelledby="public-page-gallery-heading">
        <h3 id="public-page-gallery-heading" className="text-sm font-semibold text-rally-ink">
          Gallery <span className="font-normal text-rally-subtle">({form.gallery.length} of {GALLERY_MAX})</span>
        </h3>
        {form.gallery.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2" data-testid="public-page-gallery">
            {form.gallery.map((photo, index) => (
              <li
                key={photo.url}
                data-testid="public-page-gallery-item"
                className="grid gap-2 rounded-md border border-rally-line p-2"
              >
                <div className="aspect-[4/3] overflow-hidden rounded bg-rally-paper">
                  <img
                    src={photo.url}
                    alt={photo.caption || `Gallery photo ${index + 1}`}
                    className="h-full w-full object-cover"
                  />
                </div>
                <label className="grid gap-1 text-xs font-semibold text-rally-muted">
                  Caption
                  <input
                    data-testid="public-page-gallery-caption"
                    value={photo.caption}
                    maxLength={CAPTION_MAX}
                    onChange={(event) =>
                      edit({
                        gallery: form.gallery.map((item, i) =>
                          i === index ? { ...item, caption: event.target.value } : item,
                        ),
                      })
                    }
                    className={`${INPUT_CLASS} font-normal`}
                  />
                </label>
                <button
                  type="button"
                  data-testid="public-page-gallery-remove"
                  className={`${LINK_BUTTON_CLASS} justify-self-start`}
                  onClick={() => edit({ gallery: form.gallery.filter((_, i) => i !== index) })}
                >
                  Remove photo
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="grid gap-2 rounded-md border border-dashed border-rally-line bg-rally-paper p-3">
          <label className="flex items-start gap-2 text-sm text-rally-ink">
            <input
              type="checkbox"
              data-testid="public-page-gallery-consent"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-blue-600"
            />
            <span>{GALLERY_CONSENT_LABEL}</span>
          </label>
          <PhotoUpload
            testId="public-page-gallery-upload"
            label="Add gallery photo"
            buttonLabel="Add photo"
            blockedReason={
              blocker === "full"
                ? `The gallery is full (${GALLERY_MAX} photos). Remove one to add another.`
                : blocker === "consent"
                  ? "Tick the box above first."
                  : null
            }
            upload={uploadGallery}
            onUploaded={(url) => {
              editWith((current) => ({
                gallery: [...current.gallery, { url, caption: "", consent_confirmed: true }],
              }));
              // Each photo needs its own confirmation.
              setConsent(false);
            }}
          />
        </div>
      </section>

      {/* Coaches shown */}
      <section className="mt-6 grid gap-2" aria-labelledby="public-page-coaches-heading">
        <h3 id="public-page-coaches-heading" className="text-sm font-semibold text-rally-ink">
          Coaches shown
        </h3>
        <p className="text-xs text-rally-muted">
          A photo and short bio for each coach you want on the page. Coaches you leave off show
          as a name next to their classes.
        </p>
        {coachQuery.isPending ? (
          <p className="text-sm text-rally-subtle">Loading coaches…</p>
        ) : coaches.length === 0 ? (
          <p className="text-sm text-rally-subtle" data-testid="public-page-coaches-empty">
            No coaches yet. Add coaches in People first.
          </p>
        ) : (
          <ul className="grid gap-3" data-testid="public-page-coaches">
            {coaches.map(({ coach_id, name, profile }) => (
              <li
                key={coach_id}
                data-testid="public-page-coach-row"
                className="grid gap-2 rounded-md border border-rally-line p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-rally-ink">{name}</span>
                  <label className="inline-flex items-center gap-2 text-sm text-rally-ink">
                    <input
                      type="checkbox"
                      role="switch"
                      data-testid="public-page-coach-shown"
                      aria-label={`Show ${name} on the page`}
                      checked={isCoachShown(profile)}
                      onChange={(event) =>
                        edit({
                          coach_profiles: setCoachProfile(form.coach_profiles, coach_id, {
                            shown: event.target.checked,
                          }),
                        })
                      }
                      className="size-4 accent-blue-600"
                    />
                    Shown
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  {profile?.photo_url ? (
                    <>
                      <img
                        src={profile.photo_url}
                        alt={`${name} photo`}
                        className="size-16 rounded-full border border-rally-line object-cover"
                      />
                      <button
                        type="button"
                        data-testid="public-page-coach-photo-remove"
                        className={LINK_BUTTON_CLASS}
                        onClick={() =>
                          edit({
                            coach_profiles: setCoachProfile(form.coach_profiles, coach_id, {
                              photo_url: null,
                            }),
                          })
                        }
                      >
                        Remove photo
                      </button>
                    </>
                  ) : null}
                  <PhotoUpload
                    testId={`public-page-coach-photo-${coach_id}`}
                    label={`Photo of ${name}`}
                    buttonLabel={profile?.photo_url ? "Replace photo" : "Add photo"}
                    hint="A head-and-shoulders photo works best."
                    upload={uploadCoach}
                    onUploaded={(url) =>
                      editWith((current) => ({
                        coach_profiles: setCoachProfile(current.coach_profiles, coach_id, {
                          photo_url: url,
                        }),
                      }))
                    }
                  />
                </div>
                <label className="grid gap-1 text-xs font-semibold text-rally-muted">
                  Short bio
                  <textarea
                    data-testid="public-page-coach-bio"
                    rows={2}
                    maxLength={BIO_MAX}
                    value={profile?.bio ?? ""}
                    onChange={(event) =>
                      edit({
                        coach_profiles: setCoachProfile(form.coach_profiles, coach_id, {
                          bio: event.target.value,
                        }),
                      })
                    }
                    className={`${TEXTAREA_CLASS} font-normal`}
                  />
                  <span
                    className="font-normal text-rally-subtle"
                    data-testid="public-page-coach-bio-count"
                  >
                    {(profile?.bio ?? "").length} / {BIO_MAX}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* FAQ */}
      <section className="mt-6 grid gap-2" aria-labelledby="public-page-faq-heading">
        <h3 id="public-page-faq-heading" className="text-sm font-semibold text-rally-ink">
          FAQ
        </h3>
        <p className="text-xs text-rally-muted" data-testid="public-page-faq-helper">
          Leave empty to use the standard questions.
        </p>
        {form.faqs.length > 0 && (
          <ol className="grid gap-3" data-testid="public-page-faqs">
            {form.faqs.map((faq, index) => (
              <li
                key={index}
                data-testid="public-page-faq-row"
                className="grid gap-2 rounded-md border border-rally-line p-3"
              >
                <label className="grid gap-1 text-xs font-semibold text-rally-muted">
                  Question
                  <input
                    data-testid="public-page-faq-question"
                    value={faq.question}
                    maxLength={FAQ_QUESTION_MAX}
                    onChange={(event) =>
                      edit({
                        faqs: form.faqs.map((item, i) =>
                          i === index ? { ...item, question: event.target.value } : item,
                        ),
                      })
                    }
                    className={`${INPUT_CLASS} font-normal`}
                  />
                </label>
                <label className="grid gap-1 text-xs font-semibold text-rally-muted">
                  Answer
                  <textarea
                    data-testid="public-page-faq-answer"
                    rows={3}
                    maxLength={FAQ_ANSWER_MAX}
                    value={faq.answer}
                    onChange={(event) =>
                      edit({
                        faqs: form.faqs.map((item, i) =>
                          i === index ? { ...item, answer: event.target.value } : item,
                        ),
                      })
                    }
                    className={`${TEXTAREA_CLASS} font-normal`}
                  />
                </label>
                <div className="flex flex-wrap items-center gap-1">
                  <button
                    type="button"
                    data-testid="public-page-faq-up"
                    aria-label={`Move question ${index + 1} up`}
                    disabled={index === 0}
                    className={LINK_BUTTON_CLASS}
                    onClick={() => edit({ faqs: moveItem(form.faqs, index, -1) })}
                  >
                    Move up
                  </button>
                  <button
                    type="button"
                    data-testid="public-page-faq-down"
                    aria-label={`Move question ${index + 1} down`}
                    disabled={index === form.faqs.length - 1}
                    className={LINK_BUTTON_CLASS}
                    onClick={() => edit({ faqs: moveItem(form.faqs, index, 1) })}
                  >
                    Move down
                  </button>
                  <button
                    type="button"
                    data-testid="public-page-faq-remove"
                    aria-label={`Remove question ${index + 1}`}
                    className={LINK_BUTTON_CLASS}
                    onClick={() => edit({ faqs: form.faqs.filter((_, i) => i !== index) })}
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ol>
        )}
        {form.faqs.length < FAQS_MAX ? (
          <div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              data-testid="public-page-faq-add"
              onClick={() => edit({ faqs: [...form.faqs, { question: "", answer: "" }] })}
            >
              Add question
            </Button>
          </div>
        ) : (
          <p className="text-xs text-rally-subtle">
            You have {FAQS_MAX} questions, the most the page shows.
          </p>
        )}
      </section>

      {errors.length > 0 && (
        <ul role="alert" className="mt-4 grid gap-1 text-sm font-medium text-status-red-800" data-testid="public-page-content-errors">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button
          variant={dirty ? "volt" : "secondary"}
          size="sm"
          disabled={!dirty || errors.length > 0 || mutation.isPending || query.isPending}
          onClick={() => mutation.mutate()}
          data-testid="public-page-content-save"
        >
          {mutation.isPending ? "Saving..." : "Save photos & details"}
        </Button>
        <SavedNote at={savedAt} />
        {(query.isError || mutation.isError) && (
          <p role="alert" className="text-sm font-medium text-status-red-800">
            {(mutation.error ?? query.error)?.message}
          </p>
        )}
      </div>
    </Card>
  );
}
