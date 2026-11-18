// The commit the site was built from, set by vite.config.ts: an empty hash when it was built
// without git. `dirty`: tracked files differed from the commit.
declare const __RELEASE__: { commit: string; dirty: boolean };
export const release = __RELEASE__;
