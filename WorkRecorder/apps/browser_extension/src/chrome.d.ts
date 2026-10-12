declare namespace chrome {
  namespace runtime {
    const id: string;
    const onStartup: {
      addListener(callback: () => void | Promise<void>): void;
    };
    const onInstalled: {
      addListener(callback: () => void | Promise<void>): void;
    };
    const onMessage: {
      addListener(
        callback: (message: unknown, sender: unknown, sendResponse: (response?: unknown) => void) => boolean
      ): void;
    };
    function getURL(path: string): string;
    function sendMessage(message: unknown): Promise<unknown>;
  }

  namespace action {
    const onClicked: {
      addListener(callback: (tab: tabs.Tab) => void | Promise<void>): void;
    };
  }

  namespace tabs {
    type TabChangeInfo = {
      status?: string;
      url?: string;
      title?: string;
    };

    type Tab = {
      id?: number;
      windowId?: number;
      url?: string;
      title?: string;
      width?: number;
      height?: number;
    };

    const onActivated: {
      addListener(callback: (activeInfo: { tabId: number; windowId: number }) => void | Promise<void>): void;
    };
    const onUpdated: {
      addListener(callback: (tabId: number, changeInfo: TabChangeInfo, tab: Tab) => void | Promise<void>): void;
    };

	    function query(queryInfo: { active?: boolean; lastFocusedWindow?: boolean }): Promise<Tab[]>;
	    function get(tabId: number): Promise<Tab>;
	    function sendMessage(tabId: number, message: unknown): Promise<unknown>;
    function getZoom(tabId: number): Promise<number>;
  }

  namespace scripting {
    function executeScript(injection: { target: { tabId: number }; files: string[] }): Promise<unknown[]>;
  }

  namespace storage {
    const local: {
      get(keys: string[]): Promise<Record<string, unknown>>;
      remove(keys: string[]): Promise<void>;
    };
  }

  namespace windows {
    type Window = {
      id?: number;
      left?: number;
      top?: number;
      width?: number;
      height?: number;
    };

    function get(windowId: number): Promise<Window>;
  }
}
