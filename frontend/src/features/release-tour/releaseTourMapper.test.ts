import { describe, expect, it } from "vitest";

import {
  buildReleaseTour,
  buildReleaseTours,
  buildTourSlides,
  computeTourRevision,
  selectPendingReleaseTour,
  toVersionedReleaseId,
} from "@/features/release-tour/releaseTourMapper";
import { RELEASE_REGISTRY } from "@/features/release-tour/releaseRegistry";
import { TOUR_VISUALS } from "@/features/release-tour/tourVisuals";
import type { ReleaseEntry } from "@/features/release-tour/releaseTour.types";

function makeRelease(overrides: Partial<ReleaseEntry> = {}): ReleaseEntry {
  return {
    releaseId: "2026.08",
    publishedAt: new Date("2026-08-18T00:00:00Z"),
    headline: "Test release",
    releaseTour: {
      label: "New in Heym",
      introTitle: "Intro title",
      introDescription: "Intro description",
      sectionOrder: ["alpha", "beta"],
    },
    sections: [
      {
        id: "alpha",
        title: "Alpha",
        blocks: [{ type: "prose", markdown: "alpha notes" }],
        tour: { description: "alpha tour", useCases: ["a"], tourVisual: "alpha-visual" },
      },
      {
        id: "beta",
        title: "Beta",
        blocks: [{ type: "prose", markdown: "beta notes" }],
        tour: { description: "beta tour", useCases: ["b"], tourVisual: "beta-visual" },
      },
    ],
    ...overrides,
  };
}

describe("toVersionedReleaseId", () => {
  it("versions the release id with the tour revision", () => {
    expect(toVersionedReleaseId("2026.08", "abc")).toBe("2026.08@rabc");
    expect(toVersionedReleaseId("2026.08", "def")).toBe("2026.08@rdef");
  });
});

describe("computeTourRevision", () => {
  it("is stable for the same slides", () => {
    expect(computeTourRevision(["a", "b"])).toBe(computeTourRevision(["a", "b"]));
  });

  it("changes when a slide is added, removed, or reordered", () => {
    const base = computeTourRevision(["a", "b"]);

    expect(computeTourRevision(["a", "b", "c"])).not.toBe(base);
    expect(computeTourRevision(["a"])).not.toBe(base);
    expect(computeTourRevision(["b", "a"])).not.toBe(base);
  });

  it("makes an added section reopen an already-seen release", () => {
    const before = buildReleaseTour(makeRelease());
    const after = buildReleaseTour(
      makeRelease({
        releaseTour: {
          label: "New in Heym",
          introTitle: "Intro title",
          introDescription: "Intro description",
          sectionOrder: ["alpha", "beta", "gamma"],
        },
        sections: [
          {
            id: "alpha",
            title: "Alpha",
            blocks: [{ type: "prose", markdown: "alpha notes" }],
            tour: { description: "alpha tour", useCases: ["a"], tourVisual: "alpha-visual" },
          },
          {
            id: "beta",
            title: "Beta",
            blocks: [{ type: "prose", markdown: "beta notes" }],
            tour: { description: "beta tour", useCases: ["b"], tourVisual: "beta-visual" },
          },
          {
            id: "gamma",
            title: "Gamma",
            blocks: [{ type: "prose", markdown: "gamma notes" }],
            tour: { description: "gamma tour", useCases: ["c"], tourVisual: "gamma-visual" },
          },
        ],
      }),
    );

    expect(after?.versionedReleaseId).not.toBe(before?.versionedReleaseId);
    // A viewer who already saw the old tour is pending again on the new one.
    expect(
      selectPendingReleaseTour([after!], [before!.versionedReleaseId])?.releaseId,
    ).toBe("2026.08");
  });
});

describe("buildTourSlides", () => {
  it("orders slides by sectionOrder rather than section order", () => {
    const release = makeRelease({
      releaseTour: {
        label: "New in Heym",
        introTitle: "Intro title",
        introDescription: "Intro description",
        sectionOrder: ["beta", "alpha"],
      },
    });

    expect(buildTourSlides(release).map((slide) => slide.id)).toEqual(["beta", "alpha"]);
  });

  it("skips ids in sectionOrder with no matching section", () => {
    const release = makeRelease({
      releaseTour: {
        label: "New in Heym",
        introTitle: "Intro title",
        introDescription: "Intro description",
        sectionOrder: ["alpha", "ghost", "beta"],
      },
    });

    expect(buildTourSlides(release).map((slide) => slide.id)).toEqual(["alpha", "beta"]);
  });

  it("skips sections that carry no tour metadata", () => {
    const release = makeRelease();
    release.sections[1] = { id: "beta", title: "Beta", blocks: [] };

    expect(buildTourSlides(release).map((slide) => slide.id)).toEqual(["alpha"]);
  });

  it("ignores sections left out of sectionOrder", () => {
    const release = makeRelease({
      releaseTour: {
        label: "New in Heym",
        introTitle: "Intro title",
        introDescription: "Intro description",
        sectionOrder: ["alpha"],
      },
    });

    expect(buildTourSlides(release).map((slide) => slide.id)).toEqual(["alpha"]);
  });
});

describe("buildReleaseTour", () => {
  it("builds a tour with versioned id and intro metadata", () => {
    const tour = buildReleaseTour(makeRelease(), "1");

    expect(tour).not.toBeNull();
    expect(tour?.versionedReleaseId).toBe("2026.08@r1");
    expect(tour?.introTitle).toBe("Intro title");
    expect(tour?.slides).toHaveLength(2);
  });

  it("ignores a release with no tour metadata", () => {
    expect(buildReleaseTour(makeRelease({ releaseTour: undefined }))).toBeNull();
  });

  it("ignores a release whose tour is disabled", () => {
    const release = makeRelease();
    release.releaseTour = { ...release.releaseTour!, tourEnabled: false };

    expect(buildReleaseTour(release)).toBeNull();
  });

  it("treats an absent tourEnabled flag as enabled", () => {
    const release = makeRelease();
    expect(release.releaseTour?.tourEnabled).toBeUndefined();
    expect(buildReleaseTour(release)).not.toBeNull();
  });

  it("ignores a release that resolves to zero slides", () => {
    const release = makeRelease({
      sections: [{ id: "alpha", title: "Alpha", blocks: [] }],
    });

    expect(buildReleaseTour(release)).toBeNull();
  });
});

describe("buildReleaseTours", () => {
  it("sorts releases newest first", () => {
    const older = makeRelease({
      releaseId: "2026.07",
      publishedAt: new Date("2026-07-01T00:00:00Z"),
    });
    const newer = makeRelease({
      releaseId: "2026.08",
      publishedAt: new Date("2026-08-18T00:00:00Z"),
    });

    expect(buildReleaseTours([older, newer]).map((tour) => tour.releaseId)).toEqual([
      "2026.08",
      "2026.07",
    ]);
  });

  it("drops disabled releases from the list", () => {
    const disabled = makeRelease({ releaseId: "2026.09" });
    disabled.publishedAt = new Date("2026-09-01T00:00:00Z");
    disabled.releaseTour = { ...disabled.releaseTour!, tourEnabled: false };

    expect(buildReleaseTours([makeRelease(), disabled]).map((tour) => tour.releaseId)).toEqual([
      "2026.08",
    ]);
  });
});

describe("selectPendingReleaseTour", () => {
  const tours = buildReleaseTours([
    makeRelease({ releaseId: "2026.07", publishedAt: new Date("2026-07-01T00:00:00Z") }),
    makeRelease({ releaseId: "2026.08", publishedAt: new Date("2026-08-18T00:00:00Z") }),
  ]);
  const seenId = (releaseId: string): string =>
    tours.find((tour) => tour.releaseId === releaseId)!.versionedReleaseId;

  it("returns the newest release when nothing has been seen", () => {
    expect(selectPendingReleaseTour(tours, [])?.releaseId).toBe("2026.08");
  });

  it("returns null once the newest release is seen", () => {
    expect(selectPendingReleaseTour(tours, [seenId("2026.08")])).toBeNull();
  });

  it("does not queue older unseen releases behind the newest", () => {
    expect(
      selectPendingReleaseTour(tours, [seenId("2026.08"), seenId("2026.07")]),
    ).toBeNull();
    expect(selectPendingReleaseTour(tours, [seenId("2026.07")])?.releaseId).toBe("2026.08");
  });

  it("treats a different revision of the same release as unseen", () => {
    expect(selectPendingReleaseTour(tours, ["2026.08@r0"])?.releaseId).toBe("2026.08");
  });

  it("returns null when there are no tourable releases", () => {
    expect(selectPendingReleaseTour([], [])).toBeNull();
  });
});

describe("shipped release registry", () => {
  it("resolves every registry slide to a registered visual", () => {
    const slides = buildReleaseTours(RELEASE_REGISTRY).flatMap((tour) => tour.slides);

    expect(slides.length).toBeGreaterThan(0);
    for (const slide of slides) {
      expect(TOUR_VISUALS[slide.tourVisual], `missing visual for "${slide.tourVisual}"`).toBeDefined();
    }
  });
});
