import { adminWsUrl, publicJobWsUrl, type AdminWsEvent, type PublicJobWsEvent } from "./api";

export interface AdminSocket {
  close: () => void;
}

export function connectAdminSocket(options: {
  token: string;
  onOpen: () => void;
  onClose: () => void;
  onEvent: (event: AdminWsEvent) => void;
}): AdminSocket {
  const socket = new WebSocket(adminWsUrl(options.token));
  socket.addEventListener("open", options.onOpen);
  socket.addEventListener("close", options.onClose);
  socket.addEventListener("error", options.onClose);
  socket.addEventListener("message", (message: MessageEvent<string>) => {
    try {
      options.onEvent(JSON.parse(message.data) as AdminWsEvent);
    } catch {
      return;
    }
  });
  return {
    close: () => socket.close()
  };
}

export interface PublicJobSocket {
  close: () => void;
}

/** Open a WebSocket subscription to a single public job's live status stream.
 * Accepts `?token=` because browsers cannot set WS Authorization headers. */
export function connectPublicJobSocket(options: {
  jobId: string;
  token: string;
  onOpen: () => void;
  onClose: () => void;
  onEvent: (event: PublicJobWsEvent) => void;
}): PublicJobSocket {
  const socket = new WebSocket(publicJobWsUrl(options.jobId, options.token));
  socket.addEventListener("open", options.onOpen);
  socket.addEventListener("close", options.onClose);
  socket.addEventListener("error", options.onClose);
  socket.addEventListener("message", (message: MessageEvent<string>) => {
    try {
      options.onEvent(JSON.parse(message.data) as PublicJobWsEvent);
    } catch {
      return;
    }
  });
  return {
    close: () => socket.close()
  };
}
