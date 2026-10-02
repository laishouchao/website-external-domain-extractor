"""
Playwright Stealth & Anti-Fingerprinting Toolkit.
Pure native JavaScript injection without external binary dependencies.
Masks navigator.webdriver, mocks window.chrome, spoofs WebGL, plugins, and device attributes.
"""

from typing import Dict, Any, Optional
from playwright.async_api import BrowserContext, Page


STEALTH_JS_PAYLOAD = """
(() => {
    // 1. 抹除 navigator.webdriver 自动化特征
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        delete Object.getPrototypeOf(navigator).webdriver;
    } catch (e) {}

    // 2. 模拟原生 window.chrome 运行环境
    try {
        if (!window.chrome) {
            window.chrome = {};
        }
        window.chrome.runtime = window.chrome.runtime || {
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            onMessage: { addListener: function() {}, removeListener: function() {} },
            sendMessage: function() {},
            connect: function() {}
        };
        window.chrome.loadTimes = window.chrome.loadTimes || function() {
            return {
                requestTime: (Date.now() - 1200) / 1000,
                startLoadTime: (Date.now() - 1100) / 1000,
                commitLoadTime: (Date.now() - 900) / 1000,
                finishDocumentLoadTime: (Date.now() - 300) / 1000,
                finishLoadTime: Date.now() / 1000,
                firstPaintTime: (Date.now() - 700) / 1000,
                firstPaintAfterLoadTime: 0,
                navigationType: 'Other',
                wasFetchedViaSpdy: true,
                wasNpnNegotiated: true,
                npnNegotiatedProtocol: 'h2',
                wasAlternateProtocolAvailable: false,
                connectionInfo: 'h2'
            };
        };
        window.chrome.csi = window.chrome.csi || function() {
            return {
                startE: Date.now() - 1000,
                onloadT: Date.now() - 200,
                pageT: 800,
                tran: 15
            };
        };
        window.chrome.app = window.chrome.app || {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
        };
    } catch (e) {}

    // 3. 模拟标准浏览器插件 Plugins & MimeTypes
    try {
        const fakePlugins = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
        ];
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const arr = fakePlugins.slice(0, 3);
                arr.item = (i) => arr[i];
                arr.namedItem = (name) => arr.find(p => p.name === name);
                arr.refresh = () => {};
                return arr;
            },
            configurable: true
        });
    } catch (e) {}

    // 4. 对齐中英文语言偏好
    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            configurable: true
        });
    } catch (e) {}

    // 5. 伪装 WebGL GPU 硬件特征 (规避 Google SwiftShader/llvmpipe 无头特征)
    try {
        const getParameterProto = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            // UNMASKED_VENDOR_WEBGL (0x9245)
            if (param === 37445) {
                return 'Google Inc. (NVIDIA)';
            }
            // UNMASKED_RENDERER_WEBGL (0x9246)
            if (param === 37446) {
                return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            }
            return getParameterProto.apply(this, arguments);
        };

        if (typeof WebGL2RenderingContext !== 'undefined') {
            const getParameter2Proto = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(param) {
                if (param === 37445) return 'Google Inc. (NVIDIA)';
                if (param === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParameter2Proto.apply(this, arguments);
            };
        }
    } catch (e) {}

    // 6. 伪装通知权限查询 Notification Permissions
    try {
        if (window.Notification) {
            Object.defineProperty(Notification, 'permission', {
                get: () => 'default',
                configurable: true
            });
        }
    } catch (e) {}

    // 7. 补齐窗口外框尺寸 (无头模式下 outerWidth/outerHeight 常为 0)
    try {
        if (window.outerWidth === 0) {
            window.outerWidth = window.innerWidth;
        }
        if (window.outerHeight === 0) {
            window.outerHeight = window.innerHeight + 85;
        }
    } catch (e) {}
})();
"""


async def apply_stealth_to_context(context: BrowserContext, profile: Optional[Dict[str, Any]] = None):
    """
    向 Playwright BrowserContext 注入 Native Stealth 反爬对抗脚本。
    在所有页面导航及 iframe 渲染前自动执行。
    """
    try:
        await context.add_init_script(STEALTH_JS_PAYLOAD)
    except Exception as e:
        pass
