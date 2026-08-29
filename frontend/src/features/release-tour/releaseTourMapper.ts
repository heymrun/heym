import type {
  ReleaseEntry,
  ReleaseSection,
  ReleaseTour,
  ReleaseTourSlide,
} from "@/features/release-tour/releaseTour.types";

/**
 * Derives a release's tour revision from the slides it actually contains, so adding,
 * removing, or reordering a section changes the stored id on its own and the tour
 * reopens (and the "New in Heym" dot lights up) without anyone bumping a constant.
 *
 * djb2, chosen because it is short, stable across runs, and never leaves the client -
 * a collision would only mean one tour is not re-shown, so cryptographic strength is
 * not the requirement here.
 */
export function computeTourRevision(slideIds: readonly string[]): string {
  let hash = 5381;
  for (const char of slideIds.join("|")) {
    hash = ((hash << 5) + hash + char.charCodeAt(0)) >>> 0;
  }
  return hash.toString(36);
}

export function toVersionedReleaseId(releaseId: string, revision: string): string {
  return `${releaseId}@r${revision}`;
}

function toSlide(section: ReleaseSection, releasePublishedAt: Date): ReleaseTourSlide | null {
  if (!section.tour) return null;

  return {
    id: section.id,
    title: section.title,
    description: section.tour.description,
    useCases: section.tour.useCases,
    tourVisual: section.tour.tourVisual,
    publishedAt: section.publishedAt ?? releasePublishedAt,
    docTarget: section.tour.docTarget,
  };
}

/** Resolves `sectionOrder` into slides, skipping unknown ids and untoured sections. */
export function buildTourSlides(entry: ReleaseEntry): ReleaseTourSlide[] {
  const order = entry.releaseTour?.sectionOrder ?? [];
  const sectionsById = new Map(entry.sections.map((section) => [section.id, section]));

  return order.flatMap((sectionId) => {
    const section = sectionsById.get(sectionId);
    if (!section) return [];

    const slide = toSlide(section, entry.publishedAt);
    return slide ? [slide] : [];
  });
}

/** Returns null for releases with no tour, a disabled tour, or no usable slides. */
export function buildReleaseTour(
  entry: ReleaseEntry,
  revision?: string,
): ReleaseTour | null {
  const meta = entry.releaseTour;
  if (!meta) return null;
  if (meta.tourEnabled === false) return null;

  const slides = buildTourSlides(entry);
  if (slides.length === 0) return null;

  const resolvedRevision = revision ?? computeTourRevision(slides.map((slide) => slide.id));

  return {
    releaseId: entry.releaseId,
    versionedReleaseId: toVersionedReleaseId(entry.releaseId, resolvedRevision),
    publishedAt: entry.publishedAt,
    headline: entry.headline,
    label: meta.label,
    introTitle: meta.introTitle,
    introDescription: meta.introDescription,
    introCoverImage: meta.introCoverImage,
    slides,
  };
}

/** Every tourable release, newest `publishedAt` first. */
export function buildReleaseTours(
  entries: ReleaseEntry[],
  revision?: string,
): ReleaseTour[] {
  return entries
    .flatMap((entry) => {
      const tour = buildReleaseTour(entry, revision);
      return tour ? [tour] : [];
    })
    .sort((left, right) => right.publishedAt.getTime() - left.publishedAt.getTime());
}

/**
 * Combines every enabled release into one manual-browse tour. Automatic prompts
 * still use one release at a time through `selectPendingReleaseTour`.
 */
export function buildReleaseTourCatalog(entries: ReleaseEntry[]): ReleaseTour | null {
  const tours = buildReleaseTours(entries);
  const newest = tours[0];
  if (!newest) return null;

  const slides = tours
    .flatMap((tour) => tour.slides)
    .sort((left, right) => right.publishedAt.getTime() - left.publishedAt.getTime());
  const revision = computeTourRevision(slides.map((slide) => slide.id));

  return {
    ...newest,
    releaseId: "catalog",
    versionedReleaseId: toVersionedReleaseId("catalog", revision),
    headline: "Everything new in Heym",
    introTitle: "Everything new in Heym",
    introDescription: "Browse every shipped feature, with the latest changes first.",
    slides,
  };
}

/**
 * Only the newest eligible release is ever pending. Older unseen releases are
 * skipped on purpose so upgrading across several versions shows one tour.
 */
export function selectPendingReleaseTour(
  tours: ReleaseTour[],
  seenReleaseIds: readonly string[],
): ReleaseTour | null {
  const newest = tours[0];
  if (!newest) return null;

  return seenReleaseIds.includes(newest.versionedReleaseId) ? null : newest;
}
