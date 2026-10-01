// State shared between modules.

export const state = {
  isPC: false,
  sharing: true,
  path: "",
  tab: "files",
};

// Functions one module needs from another, filled in by main.js (avoids import cycles).
export const hooks = {
  refreshStatus: async () => {},
  reloadFiles: () => {},
};
