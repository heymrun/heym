import type { Locator } from "@playwright/test";

export async function contrastRatio(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    const rgba = (value: string): number[] => value.match(/[\d.]+/g)!.map(Number);
    const composite = (base: number[], color: number[]): number[] => {
      const alpha = color[3] ?? 1;
      return base.map((channel, index) => color[index] * alpha + channel * (1 - alpha));
    };
    const luminance = (rgb: number[]): number => {
      const linear = rgb.map((channel) => {
        const value = channel / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
    };
    const backgrounds: number[][] = [];
    for (let node: Element | null = element; node; node = node.parentElement) {
      backgrounds.unshift(rgba(getComputedStyle(node).backgroundColor));
    }
    const background = backgrounds.reduce(composite, [255, 255, 255]);
    const foreground = composite(background, rgba(getComputedStyle(element).color));
    const textLuminance = luminance(foreground);
    const backgroundLuminance = luminance(background);
    return (Math.max(textLuminance, backgroundLuminance) + 0.05)
      / (Math.min(textLuminance, backgroundLuminance) + 0.05);
  });
}
