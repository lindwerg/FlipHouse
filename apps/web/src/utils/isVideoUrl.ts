// Pure predicate: is this string a usable video source URL — a known video host
// (YouTube/Vimeo/…) or a direct video file over http(s). Used by the hero
// dropzone (P1.7) to decide whether a pasted string is a valid "paste a link".

const VIDEO_HOSTS = [
  /(^|\.)youtube\.com$/,
  /(^|\.)youtu\.be$/,
  /(^|\.)vimeo\.com$/,
  /(^|\.)dailymotion\.com$/,
  /(^|\.)twitch\.tv$/,
];

const VIDEO_FILE = /\.(mp4|mov|webm|m4v)$/i;

export function isVideoUrl(value: string): boolean {
  let url: URL;

  try {
    url = new URL(value);
  } catch {
    return false;
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return false;
  }

  if (VIDEO_HOSTS.some(host => host.test(url.hostname))) {
    return true;
  }

  return VIDEO_FILE.test(url.pathname);
}
