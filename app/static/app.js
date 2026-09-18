const { createApp, ref, computed, onMounted, onUnmounted, nextTick, watch } = Vue;

const app = createApp({
    setup() {
        // Navigation & Views
        const currentView = ref('tasks'); // 'tasks' | 'detail'
        const activeTab = ref('domains');  // 'domains' | 'sitemap' | 'logs' | 'analytics'

        // Tasks Data
        const tasks = ref([]);
        const activeTask = ref(null);
        let tasksPollInterval = null;

        // Modal States
        const showCreateModal = ref(false);
        const showAdvanced = ref(false);
        const showEvidenceModal = ref(false);
        const selectedDomainForEvidence = ref('');
        const domainOccurrences = ref([]);

        // Batch Import & Multi-Select States
        const showBatchModal = ref(false);
        const showBatchAdvanced = ref(false);
        const isBatchSubmitting = ref(false);
        const batchFileInput = ref(null);
        const selectedTaskIds = ref([]);
        const deletingTaskIds = ref([]);
        const isBatchOperating = ref(false);
        const currentBatchAction = ref('');
        const batchForm = ref({
            rawUrls: '',
            nameTemplate: 'domain',
            namePrefix: '',
            autoStart: false,
            config: {
                max_depth: 10,
                max_pages: 1000,
                concurrency: 15,
                request_delay: 0.0,
                timeout: 10.0,
                scope_mode: 'root_domain',
                detect_sitemap: true,
                ignore_ssl: true,
                extract_assets: true,
                extract_text: true,
                scan_asset_content: true,
            }
        });

        // New Task Form
        const newTask = ref({
            name: '',
            target_url: '',
            config: {
                max_depth: 10,
                max_pages: 1000,
                concurrency: 15,
                request_delay: 0.0,
                timeout: 10.0,
                scope_mode: 'root_domain',
                detect_sitemap: true,
                ignore_ssl: true,
                extract_assets: true,
                extract_text: true,
                scan_asset_content: true,
            }
        });

        // External Domains Data & Filters
        const domainsList = ref([]);
        const domainsTotal = ref(0);
        const domainPage = ref(1);
        const domainFilters = ref({
            search: '',
            sourceType: '',
            riskLevel: '',
            verifyStatus: '',
            sortBy: 'occurrence_count'
        });
        const domainStats = ref({
            total_unique_domains: 0,
            unique_root_domains: 0,
            link_domains: 0,
            text_domains: 0,
            risk_stats: { critical: 0, high: 0, medium: 0, low: 0, safe: 0, pending: 0, total_risk: 0 },
            verify_stats: { unverified: 0, verified_clean: 0, verified_failed: 0, error: 0 },
            top_root_domains: [],
            top_domains: []
        });

        // Multi-select for External Domains
        const selectedDomains = ref([]);
        const isAllDomainsSelected = computed(() => {
            if (!domainsList.value.length) return false;
            return domainsList.value.every(d => selectedDomains.value.includes(d.domain));
        });

        const toggleSelectAllDomains = () => {
            if (isAllDomainsSelected.value) {
                selectedDomains.value = [];
            } else {
                selectedDomains.value = domainsList.value.map(d => d.domain);
            }
        };

        // Manual Risk Tagging Modal State
        const showTagModal = ref(false);
        const tagTargetDomain = ref(null);
        const tagForm = ref({
            risk_level: 'high',
            tags: [],
            customTag: '',
            remark: '',
            sync_to_global: false,
            match_type: 'root'
        });

        // Targeted Verification Modal State & Loading Maps
        const showVerifyModal = ref(false);
        const verifyVerdict = ref(null);
        const verifyTargetDomain = ref('');
        const verifyingMap = ref({});
        const batchVerifying = ref(false);
        const evaluatingRules = ref(false);

        // Global Threat Intelligence Profiles Modal State
        const showRiskProfilesModal = ref(false);
        const riskProfiles = ref([]);
        const riskProfilesTotal = ref(0);
        const riskProfilePage = ref(1);
        const riskProfileSearch = ref('');
        const riskProfileLevelFilter = ref('');
        const showAddProfileForm = ref(false);
        const showBatchImportProfilesForm = ref(false);
        const batchImportProfilesText = ref('');
        const isImportingProfiles = ref(false);
        const isSyncingHistory = ref(false);
        const newProfile = ref({
            domain: '',
            match_type: 'root',
            risk_level: 'high',
            category: '',
            tags: '',
            remark: '',
            sync_to_history: true
        });

        // Discovered Subdomains Data & Filters
        const subdomainsList = ref([]);
        const subdomainsTotal = ref(0);
        const subdomainPage = ref(1);
        const subdomainFilters = ref({
            search: '',
            sourceType: '',
            sortBy: 'occurrence_count'
        });
        const subdomainStats = ref({
            total_unique_subdomains: 0,
            link_subdomains: 0,
            text_subdomains: 0,
            top_subdomains: []
        });

        // Global External Domains Repository Data & Filters
        const globalDomainsList = ref([]);
        const globalDomainsTotal = ref(0);
        const globalDomainPage = ref(1);
        const globalDomainFilters = ref({
            search: '',
            sourceType: '',
            riskLevel: '',
            verifyStatus: '',
            minTasks: '',
            sortBy: 'total_occurrences'
        });
        const globalDomainStats = ref({
            total_unique_domains: 0,
            unique_root_domains: 0,
            total_tasks: 0,
            total_occurrences: 0,
            shared_domains_count: 0,
            top_roots: [],
            top_shared_domains: []
        });

        // Associated Tasks Modal State
        const showAssociatedTasksModal = ref(false);
        const selectedDomainForTasks = ref('');
        const associatedTasksList = ref([]);
        const isLoadingAssociatedTasks = ref(false);

        // Sitemap Pages Data & Filters
        const sitemapPages = ref([]);
        const sitemapTotal = ref(0);
        const sitemapPage = ref(1);
        const sitemapFilters = ref({
            search: '',
            depth: '',
            statusCode: ''
        });

        // Logs & Terminal
        const logs = ref([]);
        const autoScrollLogs = ref(true);
        const terminalRef = ref(null);
        const liveProgress = ref({});
        let eventSource = null;

        // Computed Properties
        const runningTasksCount = computed(() => {
            return tasks.value.filter(t => t.status === 'running').length;
        });

        const totalPagesCrawled = computed(() => {
            return tasks.value.reduce((acc, t) => acc + (t.pages_crawled || 0), 0);
        });

        const totalExtDomainsFound = computed(() => {
            return tasks.value.reduce((acc, t) => acc + (t.external_domains_count || 0), 0);
        });

        const totalSubdomainsFound = computed(() => {
            return tasks.value.reduce((acc, t) => acc + (t.subdomains_count || 0), 0);
        });

        const parsedBatchUrls = computed(() => {
            if (!batchForm.value.rawUrls) return [];
            const lines = batchForm.value.rawUrls.split('\n');
            const valid = [];
            const seen = new Set();
            for (let line of lines) {
                let str = line.trim();
                if (!str || str.startsWith('#')) continue;
                if (!str.startsWith('http://') && !str.startsWith('https://')) {
                    str = 'https://' + str;
                }
                if (!seen.has(str)) {
                    seen.add(str);
                    valid.push(str);
                }
            }
            return valid;
        });

        const isAllSelected = computed(() => {
            return tasks.value.length > 0 && selectedTaskIds.value.length === tasks.value.length;
        });

        // ==================== Task Methods ====================

        const loadTasks = async () => {
            try {
                const res = await fetch('/api/tasks');
                if (res.ok) {
                    const data = await res.json();
                    tasks.value = data.tasks || [];
                    // If viewing details, update active task reference
                    if (activeTask.value) {
                        const updated = tasks.value.find(t => t.id === activeTask.value.id);
                        if (updated) {
                            activeTask.value = { ...activeTask.value, ...updated };
                        }
                    }
                }
            } catch (e) {
                console.error("Failed to load tasks", e);
            }
        };

        const openCreateModal = () => {
            newTask.value.name = `扫描任务_${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`;
            newTask.value.target_url = '';
            showCreateModal.value = true;
        };

        const submitCreateTask = async () => {
            if (!newTask.value.name.trim() || !newTask.value.target_url.trim()) {
                alert("请填写任务名称和目标站点 URL");
                return;
            }

            try {
                const res = await fetch('/api/tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newTask.value)
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    showCreateModal.value = false;
                    await loadTasks();
                    // Automatically enter task and start
                    enterTask(data.task);
                    await startTask(data.task.id);
                } else {
                    alert("创建任务失败: " + (data.detail || "未知错误"));
                }
            } catch (e) {
                alert("创建任务异常: " + e.message);
            }
        };

        const openBatchModal = () => {
            batchForm.value.rawUrls = '';
            batchForm.value.nameTemplate = 'domain';
            batchForm.value.namePrefix = '';
            batchForm.value.autoStart = false;
            showBatchAdvanced.value = false;
            showBatchModal.value = true;
        };

        const handleBatchFileUpload = (event) => {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                const text = e.target.result;
                if (text) {
                    if (batchForm.value.rawUrls.trim()) {
                        batchForm.value.rawUrls += '\n' + text;
                    } else {
                        batchForm.value.rawUrls = text;
                    }
                }
            };
            reader.readAsText(file);
            event.target.value = '';
        };

        const submitBatchImport = async () => {
            const urls = parsedBatchUrls.value;
            if (urls.length === 0) {
                alert("请输入或导入至少一个有效待测站点 URL");
                return;
            }
            isBatchSubmitting.value = true;
            try {
                const payload = {
                    urls: urls,
                    name_prefix: batchForm.value.namePrefix,
                    name_template: batchForm.value.nameTemplate,
                    auto_start: batchForm.value.autoStart,
                    config: batchForm.value.config
                };
                const res = await fetch('/api/tasks/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    showBatchModal.value = false;
                    await loadTasks();
                    const startMsg = data.started_count > 0 ? `，并已同时并发启动 ${data.started_count} 个任务进行扫描` : '';
                    alert(`成功批量导入并创建 ${data.created_count} 个扫描任务${startMsg}！`);
                } else {
                    alert("批量创建任务失败: " + (data.detail || "未知错误"));
                }
            } catch (e) {
                alert("批量导入异常: " + e.message);
            } finally {
                isBatchSubmitting.value = false;
            }
        };

        const toggleSelectAll = () => {
            if (isAllSelected.value) {
                selectedTaskIds.value = [];
            } else {
                selectedTaskIds.value = tasks.value.map(t => t.id);
            }
        };

        const executeBatchAction = async (action) => {
            const ids = selectedTaskIds.value;
            if (ids.length === 0) return;
            const actionMap = {
                start: '批量启动',
                pause: '批量暂停',
                resume: '批量继续',
                stop: '批量停止',
                delete: '批量删除'
            };
            const actionName = actionMap[action] || action;
            if (action === 'delete') {
                if (!confirm(`确定要批量删除所选的 ${ids.length} 个任务及所有关联扫描数据吗？此操作不可撤销。`)) return;
            }
            isBatchOperating.value = true;
            currentBatchAction.value = action;
            try {
                const res = await fetch('/api/tasks/batch-action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_ids: ids, action: action })
                });
                const data = await res.json().catch(() => ({}));
                if (res.ok && data.success) {
                    if (action === 'delete') {
                        selectedTaskIds.value = [];
                    }
                    await loadTasks();
                } else {
                    alert(`执行${actionName}失败: ` + (data.detail || data.message || "未知错误"));
                }
            } catch (e) {
                alert(`执行${actionName}异常: ` + e.message);
            } finally {
                isBatchOperating.value = false;
                currentBatchAction.value = '';
            }
        };

        const enterTask = async (task) => {
            activeTask.value = task;
            currentView.value = 'detail';
            activeTab.value = 'domains';
            logs.value = [];
            domainPage.value = 1;
            subdomainPage.value = 1;
            sitemapPage.value = 1;

            // Load initial data for this task
            await Promise.all([
                loadDomains(1),
                loadSubdomains(1),
                loadSitemap(1),
                loadDomainStats(),
                loadSubdomainStats(),
                loadTaskLogs()
            ]);

            // Setup SSE stream
            setupEventSource(task.id);
        };

        const startTask = async (taskId) => {
            try {
                const res = await fetch(`/api/tasks/${taskId}/start`, { method: 'POST' });
                if (res.ok) {
                    await loadTasks();
                    if (activeTask.value && activeTask.value.id === taskId) {
                        activeTask.value.status = 'running';
                    }
                }
            } catch (e) {
                console.error(e);
            }
        };

        const pauseTask = async (taskId) => {
            try {
                const res = await fetch(`/api/tasks/${taskId}/pause`, { method: 'POST' });
                if (res.ok) {
                    await loadTasks();
                    if (activeTask.value && activeTask.value.id === taskId) {
                        activeTask.value.status = 'paused';
                    }
                }
            } catch (e) {
                console.error(e);
            }
        };

        const resumeTask = async (taskId) => {
            try {
                const res = await fetch(`/api/tasks/${taskId}/resume`, { method: 'POST' });
                if (res.ok) {
                    await loadTasks();
                    if (activeTask.value && activeTask.value.id === taskId) {
                        activeTask.value.status = 'running';
                    }
                }
            } catch (e) {
                console.error(e);
            }
        };

        const stopTask = async (taskId) => {
            try {
                const res = await fetch(`/api/tasks/${taskId}/stop`, { method: 'POST' });
                if (res.ok) {
                    await loadTasks();
                    if (activeTask.value && activeTask.value.id === taskId) {
                        activeTask.value.status = 'stopped';
                    }
                }
            } catch (e) {
                console.error(e);
            }
        };

        const retryTask = async (taskId) => {
            if (!confirm("确定要重置当前任务所有已抓取的数据并重新开始吗？")) return;
            try {
                const res = await fetch(`/api/tasks/${taskId}/retry`, { method: 'POST' });
                if (res.ok) {
                    logs.value = [];
                    await loadTasks();
                    if (activeTask.value && activeTask.value.id === taskId) {
                        activeTask.value.status = 'running';
                        activeTask.value.pages_crawled = 0;
                        activeTask.value.external_domains_count = 0;
                        activeTask.value.subdomains_count = 0;
                        await loadDomains(1);
                        await loadSubdomains(1);
                        await loadSitemap(1);
                        await loadDomainStats();
                        await loadSubdomainStats();
                    }
                }
            } catch (e) {
                console.error(e);
            }
        };

        const deleteTask = async (taskId) => {
            if (!confirm("确定要删除此任务及所有扫描产生的数据吗？此操作不可撤销。")) return;
            deletingTaskIds.value.push(taskId);
            try {
                const res = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
                const data = await res.json().catch(() => ({}));
                if (res.ok && (data.success !== false)) {
                    if (activeTask.value && activeTask.value.id === taskId) {
                        closeEventSource();
                        currentView.value = 'tasks';
                        activeTask.value = null;
                    }
                    await loadTasks();
                } else {
                    alert("删除任务失败: " + (data.detail || data.message || "服务器响应错误"));
                }
            } catch (e) {
                console.error(e);
                alert("删除任务请求异常: " + e.message);
            } finally {
                deletingTaskIds.value = deletingTaskIds.value.filter(id => id !== taskId);
            }
        };

        // ==================== SSE Stream & Logs ====================

        const setupEventSource = (taskId) => {
            closeEventSource();
            eventSource = new EventSource(`/api/tasks/${taskId}/events`);

            eventSource.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    handleRealtimeEvent(msg);
                } catch (err) {
                    // Ignore ping comments
                }
            };

            eventSource.onerror = () => {
                // Let browser reconnect automatically
            };
        };

        const closeEventSource = () => {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
        };

        const handleRealtimeEvent = (msg) => {
            const { type, data } = msg;
            if (type === 'log') {
                logs.value.push(data);
                if (logs.value.length > 500) logs.value.shift();
                if (autoScrollLogs.value) {
                    nextTick(() => {
                        if (terminalRef.value) {
                            terminalRef.value.scrollTop = terminalRef.value.scrollHeight;
                        }
                    });
                }
            } else if (type === 'progress') {
                liveProgress.value = data;
                if (activeTask.value) {
                    activeTask.value.pages_crawled = data.pages_crawled;
                    activeTask.value.pages_total = data.pages_total;
                    activeTask.value.external_domains_count = data.external_domains_count;
                    if (data.subdomains_count !== undefined) {
                        activeTask.value.subdomains_count = data.subdomains_count;
                    }
                    activeTask.value.current_url = data.current_url;
                    activeTask.value.current_speed = data.speed !== undefined ? data.speed : (data.current_speed !== undefined ? data.current_speed : 0);
                    activeTask.value.avg_speed = data.avg_speed !== undefined ? data.avg_speed : 0;
                }
            } else if (type === 'status') {
                if (activeTask.value) {
                    activeTask.value.status = data.status;
                }
            } else if (type === 'complete') {
                if (activeTask.value) {
                    activeTask.value.status = data.status;
                    activeTask.value.pages_crawled = data.pages_crawled;
                    activeTask.value.external_domains_count = data.external_domains_count;
                    if (data.subdomains_count !== undefined) {
                        activeTask.value.subdomains_count = data.subdomains_count;
                    }
                    activeTask.value.current_speed = 0.0;
                    activeTask.value.avg_speed = data.avg_speed !== undefined ? data.avg_speed : (activeTask.value.avg_speed || 0);
                }
                loadDomains(1);
                loadSubdomains(1);
                loadSitemap(1);
                loadDomainStats();
                loadSubdomainStats();
            }
        };

        const loadTaskLogs = async () => {
            if (!activeTask.value) return;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/logs?limit=100`);
                if (res.ok) {
                    const data = await res.json();
                    logs.value = data.logs || [];
                    nextTick(() => {
                        if (terminalRef.value) {
                            terminalRef.value.scrollTop = terminalRef.value.scrollHeight;
                        }
                    });
                }
            } catch (e) {
                console.error(e);
            }
        };

        const clearLogs = () => {
            logs.value = [];
        };

        // ==================== External Domains ====================

        const loadDomains = async (page = 1) => {
            if (!activeTask.value) return;
            domainPage.value = page;
            const offset = (page - 1) * 50;
            
            const params = new URLSearchParams({
                limit: 50,
                offset: offset,
                sort_by: domainFilters.value.sortBy || 'occurrence_count',
                order: 'DESC'
            });

            if (domainFilters.value.search) params.append('search', domainFilters.value.search.trim());
            if (domainFilters.value.sourceType === 'link') params.append('has_link', 1);
            if (domainFilters.value.sourceType === 'text') params.append('has_text', 1);
            if (domainFilters.value.sourceType === 'asset') params.append('source_type', 'asset');
            if (domainFilters.value.riskLevel) params.append('risk_level', domainFilters.value.riskLevel);
            if (domainFilters.value.verifyStatus) params.append('verify_status', domainFilters.value.verifyStatus);

            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    domainsList.value = data.domains || [];
                    domainsTotal.value = data.total || 0;
                }
            } catch (e) {
                console.error(e);
            }
        };

        const loadDomainStats = async () => {
            if (!activeTask.value) return;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/stats`);
                if (res.ok) {
                    domainStats.value = await res.json();
                }
            } catch (e) {
                console.error(e);
            }
        };

        const cleaningDomains = ref(false);

        const cleanDomains = async (taskId) => {
            if (!taskId) return;
            if (!confirm("确定要对该任务的外部域名进行深度清洗吗？\n将严格对照 IANA 国际官方注册根域名库与代码语法规则，自动剔除类似 window.open、e.target 等伪域名。")) {
                return;
            }
            cleaningDomains.value = true;
            try {
                const res = await fetch(`/api/tasks/${taskId}/domains/clean`, {
                    method: 'POST'
                });
                if (res.ok) {
                    const data = await res.json();
                    alert(`清洗完成！\n已剔除无效伪域名: ${data.deleted_domains_count} 个\n剔除记录数: ${data.deleted_occurrences_count} 条\n当前剩余有效域名: ${data.remaining_domains_count} 个`);
                    if (activeTask.value && activeTask.value.id === taskId) {
                        activeTask.value.external_domains_count = data.remaining_domains_count;
                    }
                    await loadDomains(1);
                    await loadDomainStats();
                    await loadTasks();
                } else {
                    const err = await res.json();
                    alert(`清洗失败: ${err.detail || '未知错误'}`);
                }
            } catch (e) {
                console.error(e);
                alert(`请求失败: ${e.message}`);
            } finally {
                cleaningDomains.value = false;
            }
        };

        // ==================== Discovered Subdomains ====================

        const loadSubdomains = async (page = 1) => {
            if (!activeTask.value) return;
            subdomainPage.value = page;
            const offset = (page - 1) * 50;
            
            const params = new URLSearchParams({
                limit: 50,
                offset: offset,
                sort_by: subdomainFilters.value.sortBy || 'occurrence_count',
                order: 'DESC'
            });

            if (subdomainFilters.value.search) params.append('search', subdomainFilters.value.search.trim());
            if (subdomainFilters.value.sourceType === 'link') params.append('has_link', 1);
            if (subdomainFilters.value.sourceType === 'text') params.append('has_text', 1);

            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/subdomains?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    subdomainsList.value = data.subdomains || [];
                    subdomainsTotal.value = data.total || 0;
                }
            } catch (e) {
                console.error(e);
            }
        };

        const loadSubdomainStats = async () => {
            if (!activeTask.value) return;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/subdomains/stats`);
                if (res.ok) {
                    subdomainStats.value = await res.json();
                }
            } catch (e) {
                console.error(e);
            }
        };


        const openEvidenceModal = async (domain) => {
            if (!activeTask.value) return;
            selectedDomainForEvidence.value = domain;
            domainOccurrences.value = [];
            showEvidenceModal.value = true;

            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/${encodeURIComponent(domain)}/occurrences?limit=50`);
                if (res.ok) {
                    const data = await res.json();
                    domainOccurrences.value = data.occurrences || [];
                }
            } catch (e) {
                console.error(e);
            }
        };

        // ==================== Sitemap Pages ====================

        const loadSitemap = async (page = 1) => {
            if (!activeTask.value) return;
            sitemapPage.value = page;
            const offset = (page - 1) * 50;

            const params = new URLSearchParams({
                limit: 50,
                offset: offset
            });

            if (sitemapFilters.value.search) params.append('search', sitemapFilters.value.search.trim());
            if (sitemapFilters.value.depth !== '') params.append('depth', sitemapFilters.value.depth);
            if (sitemapFilters.value.statusCode !== '') params.append('status_code', sitemapFilters.value.statusCode);

            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/pages?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    sitemapPages.value = data.pages || [];
                    sitemapTotal.value = data.total || 0;
                }
            } catch (e) {
                console.error(e);
            }
        };

        // ==================== Helpers ====================

        const getProgressPercent = (t) => {
            if (!t.pages_total || t.pages_total === 0) return 0;
            return Math.min(100, Math.round((t.pages_crawled / t.pages_total) * 100));
        };

        const getStatusLabel = (status) => {
            const map = {
                pending: '待启动',
                running: '正在扫描',
                paused: '已暂停',
                completed: '已完成',
                stopped: '已停止',
                failed: '失败'
            };
            return map[status] || status;
        };

        const getStatusBadgeClass = (status) => {
            const map = {
                pending: 'bg-slate-800 text-slate-400 border border-slate-700',
                running: 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/60',
                paused: 'bg-amber-950/80 text-amber-300 border border-amber-800/60',
                completed: 'bg-sky-950/80 text-sky-300 border border-sky-800/60',
                stopped: 'bg-slate-800 text-slate-400 border border-slate-700',
                failed: 'bg-rose-950/80 text-rose-300 border border-rose-800/60'
            };
            return map[status] || 'bg-slate-800 text-slate-300';
        };

        const getLogLevelClass = (level) => {
            const map = {
                INFO: 'text-sky-400',
                WARN: 'text-amber-400',
                ERROR: 'text-rose-400',
                SUCCESS: 'text-emerald-400'
            };
            return map[level] || 'text-slate-400';
        };

        // ==================== Global External Domains Repository ====================

        const switchView = (viewName) => {
            currentView.value = viewName;
            const url = new URL(window.location.href);
            if (viewName === 'global_domains') {
                url.searchParams.set('view', 'global_domains');
                url.searchParams.delete('task_id');
                loadGlobalDomains(1);
                loadGlobalDomainStats();
            } else if (viewName === 'tasks') {
                url.searchParams.delete('view');
                url.searchParams.delete('task_id');
                loadTasks();
                loadGlobalDomainStats();
            }
            window.history.replaceState({}, '', url.toString());
        };

        const loadGlobalDomains = async (page = 1) => {
            globalDomainPage.value = page;
            const offset = (page - 1) * 50;

            const params = new URLSearchParams({
                limit: 50,
                offset: offset,
                sort_by: globalDomainFilters.value.sortBy || 'total_occurrences',
                order: 'DESC'
            });

            if (globalDomainFilters.value.search) {
                params.append('search', globalDomainFilters.value.search.trim());
            }
            if (globalDomainFilters.value.sourceType === 'link') {
                params.append('has_link', 1);
            }
            if (globalDomainFilters.value.sourceType === 'text') {
                params.append('has_text', 1);
            }
            if (globalDomainFilters.value.riskLevel) {
                params.append('risk_level', globalDomainFilters.value.riskLevel);
            }
            if (globalDomainFilters.value.verifyStatus) {
                params.append('verify_status', globalDomainFilters.value.verifyStatus);
            }
            if (globalDomainFilters.value.minTasks) {
                params.append('min_tasks', globalDomainFilters.value.minTasks);
            }

            try {
                const res = await fetch(`/api/global-domains?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    globalDomainsList.value = data.domains || [];
                    globalDomainsTotal.value = data.total || 0;
                }
            } catch (e) {
                console.error("Failed to load global domains:", e);
            }
        };

        const loadGlobalDomainStats = async () => {
            try {
                const res = await fetch('/api/global-domains/stats');
                if (res.ok) {
                    globalDomainStats.value = await res.json();
                }
            } catch (e) {
                console.error("Failed to load global domain stats:", e);
            }
        };

        const openAssociatedTasksModal = async (domain) => {
            selectedDomainForTasks.value = domain;
            associatedTasksList.value = [];
            isLoadingAssociatedTasks.value = true;
            showAssociatedTasksModal.value = true;

            try {
                const res = await fetch(`/api/global-domains/${encodeURIComponent(domain)}/tasks`);
                if (res.ok) {
                    const data = await res.json();
                    associatedTasksList.value = data.tasks || [];
                }
            } catch (e) {
                console.error("Failed to load associated tasks:", e);
            } finally {
                isLoadingAssociatedTasks.value = false;
            }
        };

        const jumpToTaskDetail = async (taskId) => {
            showAssociatedTasksModal.value = false;
            let target = tasks.value.find(t => t.id === taskId);
            if (!target) {
                try {
                    const res = await fetch(`/api/tasks/${taskId}`);
                    if (res.ok) {
                        target = await res.json();
                    }
                } catch (e) {
                    console.error("Failed to fetch task:", e);
                }
            }
            if (target) {
                await enterTask(target);
                activeTab.value = 'domains';
            }
        };

        // Filter helpers
        const filterByRisk = (level) => {
            domainFilters.value.riskLevel = domainFilters.value.riskLevel === level ? '' : level;
            loadDomains(1);
        };

        const filterByVerify = (status) => {
            domainFilters.value.verifyStatus = domainFilters.value.verifyStatus === status ? '' : status;
            loadDomains(1);
        };

        const filterGlobalByRisk = (level) => {
            globalDomainFilters.value.riskLevel = globalDomainFilters.value.riskLevel === level ? '' : level;
            loadGlobalDomains(1);
        };

        const filterGlobalByVerify = (status) => {
            globalDomainFilters.value.verifyStatus = globalDomainFilters.value.verifyStatus === status ? '' : status;
            loadGlobalDomains(1);
        };

        // Open Risk Tagging Modal
        const openTagModal = (domainItem) => {
            tagTargetDomain.value = domainItem;
            tagForm.value = {
                risk_level: domainItem.risk_level && domainItem.risk_level !== 'pending' ? domainItem.risk_level : 'high',
                tags: Array.isArray(domainItem.risk_tags) ? [...domainItem.risk_tags] : [],
                customTag: '',
                remark: domainItem.risk_remark || '',
                sync_to_global: false,
                match_type: 'root'
            };
            showTagModal.value = true;
        };

        const toggleTag = (tagName) => {
            const idx = tagForm.value.tags.indexOf(tagName);
            if (idx >= 0) {
                tagForm.value.tags.splice(idx, 1);
            } else {
                tagForm.value.tags.push(tagName);
            }
        };

        const addCustomTag = () => {
            const t = (tagForm.value.customTag || '').trim();
            if (t && !tagForm.value.tags.includes(t)) {
                tagForm.value.tags.push(t);
                tagForm.value.customTag = '';
            }
        };

        const saveTagForm = async () => {
            if (!activeTask.value || !tagTargetDomain.value) return;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/${encodeURIComponent(tagTargetDomain.value.domain)}/risk`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        risk_level: tagForm.value.risk_level,
                        tags: tagForm.value.tags,
                        remark: tagForm.value.remark,
                        sync_to_global: tagForm.value.sync_to_global,
                        match_type: tagForm.value.match_type
                    })
                });
                if (res.ok) {
                    showTagModal.value = false;
                    await loadDomains(domainPage.value);
                    await loadDomainStats();
                    if (tagForm.value.sync_to_global) {
                        await loadGlobalDomainStats();
                    }
                } else {
                    const err = await res.json();
                    alert("保存研判结果失败: " + (err.detail || "未知错误"));
                }
            } catch (e) {
                alert("保存研判异常: " + e.message);
            }
        };

        // Targeted Remediation Verification
        const verifySingleDomain = async (domain) => {
            if (!activeTask.value) return;
            verifyingMap.value[domain] = true;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/${encodeURIComponent(domain)}/verify`, {
                    method: 'POST'
                });
                if (res.ok) {
                    const data = await res.json();
                    const item = domainsList.value.find(d => d.domain === domain);
                    if (item && data.verdict) {
                        item.verify_status = data.verdict.verify_status;
                        item.verify_time = data.verdict.verify_time;
                        item.verify_detail = JSON.stringify(data.verdict);
                    }
                    await loadDomainStats();
                    showVerifyReport(data.verdict, domain);
                } else {
                    const err = await res.json();
                    alert("复测请求失败: " + (err.detail || "未知错误"));
                }
            } catch (e) {
                alert("复测请求异常: " + e.message);
            } finally {
                verifyingMap.value[domain] = false;
            }
        };

        const showVerifyReport = (domainItemOrVerdict, domainName = '') => {
            if (!domainItemOrVerdict) return;
            if (domainItemOrVerdict.details && domainItemOrVerdict.summary) {
                verifyVerdict.value = domainItemOrVerdict;
                verifyTargetDomain.value = domainName;
            } else {
                verifyTargetDomain.value = domainItemOrVerdict.domain;
                try {
                    verifyVerdict.value = typeof domainItemOrVerdict.verify_detail === 'string'
                        ? JSON.parse(domainItemOrVerdict.verify_detail)
                        : domainItemOrVerdict.verify_detail;
                } catch (e) {
                    verifyVerdict.value = {
                        verify_status: domainItemOrVerdict.verify_status,
                        verify_time: domainItemOrVerdict.verify_time,
                        summary: "暂无更详细复测快照",
                        details: []
                    };
                }
            }
            showVerifyModal.value = true;
        };

        const batchVerifySelected = async () => {
            if (!activeTask.value || !selectedDomains.value.length) return;
            batchVerifying.value = true;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/batch-verify`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domains: selectedDomains.value })
                });
                if (res.ok) {
                    await loadDomains(domainPage.value);
                    await loadDomainStats();
                    alert(`批量复测完成！已复测 ${selectedDomains.value.length} 个域名。`);
                } else {
                    alert("批量复测失败");
                }
            } catch (e) {
                alert("批量复测异常: " + e.message);
            } finally {
                batchVerifying.value = false;
            }
        };

        const batchSetRisk = async (level) => {
            if (!activeTask.value || !selectedDomains.value.length) return;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/batch-risk`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        domains: selectedDomains.value,
                        risk_level: level,
                        tags: [],
                        remark: '批量人工标记'
                    })
                });
                if (res.ok) {
                    selectedDomains.value = [];
                    await loadDomains(domainPage.value);
                    await loadDomainStats();
                } else {
                    alert("批量标记失败");
                }
            } catch (e) {
                alert("批量标记异常: " + e.message);
            }
        };

        const evaluateRulesForTask = async (taskId) => {
            if (!taskId) return;
            evaluatingRules.value = true;
            try {
                const res = await fetch(`/api/tasks/${taskId}/domains/evaluate-rules`, {
                    method: 'POST'
                });
                if (res.ok) {
                    const data = await res.json();
                    alert(`初筛完成！已对全站 ${data.result.total} 个外部域名进行智能评估，重新评定 ${data.result.evaluated_count} 个未人工认定的域名。`);
                    await loadDomains(1);
                    await loadDomainStats();
                } else {
                    alert("评估失败");
                }
            } catch (e) {
                alert("评估异常: " + e.message);
            } finally {
                evaluatingRules.value = false;
            }
        };

        // Threat Intel Management Functions
        const openRiskProfilesModal = () => {
            showRiskProfilesModal.value = true;
            loadRiskProfiles(1);
        };

        const loadRiskProfiles = async (page = 1) => {
            riskProfilePage.value = page;
            const offset = (page - 1) * 50;
            const params = new URLSearchParams({ limit: 50, offset });
            if (riskProfileSearch.value) params.append('search', riskProfileSearch.value.trim());
            if (riskProfileLevelFilter.value) params.append('risk_level', riskProfileLevelFilter.value);

            try {
                const res = await fetch(`/api/risk-profiles?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    riskProfiles.value = data.profiles || [];
                    riskProfilesTotal.value = data.total || 0;
                }
            } catch (e) {
                console.error(e);
            }
        };

        const submitAddProfile = async () => {
            if (!newProfile.value.domain.trim()) {
                alert("请输入域名或根域名");
                return;
            }
            try {
                const tagsArr = newProfile.value.tags
                    ? newProfile.value.tags.split(/[,，\s]+/).filter(Boolean)
                    : [];
                const res = await fetch('/api/risk-profiles', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        domain: newProfile.value.domain.trim(),
                        match_type: newProfile.value.match_type,
                        risk_level: newProfile.value.risk_level,
                        category: newProfile.value.category,
                        tags: tagsArr,
                        remark: newProfile.value.remark,
                        sync_to_history: newProfile.value.sync_to_history
                    })
                });
                if (res.ok) {
                    showAddProfileForm.value = false;
                    newProfile.value = {
                        domain: '',
                        match_type: 'root',
                        risk_level: 'high',
                        category: '',
                        tags: '',
                        remark: '',
                        sync_to_history: true
                    };
                    await loadRiskProfiles(1);
                    if (activeTask.value) {
                        await loadDomains(1);
                        await loadDomainStats();
                    }
                    await loadGlobalDomainStats();
                } else {
                    const err = await res.json();
                    alert("添加失败: " + (err.detail || "未知错误"));
                }
            } catch (e) {
                alert("添加请求异常: " + e.message);
            }
        };

        const deleteRiskProfile = async (id, domain) => {
            if (!confirm(`确定要从风险情报库中删除规则 [${domain}] 吗？`)) return;
            try {
                const res = await fetch(`/api/risk-profiles/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    await loadRiskProfiles(riskProfilePage.value);
                } else {
                    alert("删除失败");
                }
            } catch (e) {
                alert("删除异常: " + e.message);
            }
        };

        const submitBatchImportProfiles = async () => {
            const raw = (batchImportProfilesText.value || '').trim();
            if (!raw) {
                alert("请输入要导入的域名列表");
                return;
            }
            isImportingProfiles.value = true;
            try {
                const lines = raw.split('\n');
                const items = [];
                for (const line of lines) {
                    const l = line.trim();
                    if (!l || l.startsWith('#')) continue;
                    const parts = l.split(/[,，\t]+/);
                    const dom = parts[0].trim();
                    const level = parts[1] ? parts[1].trim() : 'high';
                    const category = parts[2] ? parts[2].trim() : '';
                    const remark = parts[3] ? parts[3].trim() : '批量导入情报';
                    items.push({
                        domain: dom,
                        match_type: 'root',
                        risk_level: level,
                        category: category,
                        tags: category ? [category] : [],
                        remark: remark,
                        sync_to_history: true
                    });
                }

                const res = await fetch('/api/risk-profiles/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items, sync_to_history: true })
                });
                if (res.ok) {
                    const data = await res.json();
                    alert(`导入成功！共导入 ${data.imported_count} 条风险根域名情报并完成历史回溯！`);
                    batchImportProfilesText.value = '';
                    showBatchImportProfilesForm.value = false;
                    await loadRiskProfiles(1);
                    if (activeTask.value) {
                        await loadDomains(1);
                        await loadDomainStats();
                    }
                    await loadGlobalDomainStats();
                } else {
                    alert("批量导入失败");
                }
            } catch (e) {
                alert("导入异常: " + e.message);
            } finally {
                isImportingProfiles.value = false;
            }
        };

        const syncAllProfilesToHistory = async () => {
            isSyncingHistory.value = true;
            try {
                const res = await fetch('/api/risk-profiles/sync-history', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    alert(`历史全量回溯完成！比对 ${data.result.profile_count} 条情报规则，已在全库中更新标记 ${data.result.updated_domains} 条外部域名。`);
                    if (activeTask.value) {
                        await loadDomains(domainPage.value);
                        await loadDomainStats();
                    }
                    await loadGlobalDomainStats();
                } else {
                    alert("回溯失败");
                }
            } catch (e) {
                alert("回溯异常: " + e.message);
            } finally {
                isSyncingHistory.value = false;
            }
        };

        // Lifecycle Hooks
        onMounted(async () => {
            await loadTasks();
            await loadGlobalDomainStats();

            // Auto-enter task or view if URL param is present
            const urlParams = new URLSearchParams(window.location.search);
            const viewParam = urlParams.get('view');
            const taskIdParam = urlParams.get('task_id');
            const tabParam = urlParams.get('tab');
            const evidenceParam = urlParams.get('evidence');

            if (viewParam === 'global_domains') {
                currentView.value = 'global_domains';
                await loadGlobalDomains(1);
                const domainParam = urlParams.get('modal_domain');
                if (domainParam) {
                    await nextTick();
                    openAssociatedTasksModal(domainParam);
                }
            } else if (taskIdParam) {
                const target = tasks.value.find(t => t.id == taskIdParam);
                if (target) {
                    await enterTask(target);
                    if (tabParam) activeTab.value = tabParam;
                    if (evidenceParam) {
                        await nextTick();
                        openEvidenceModal(evidenceParam);
                    }
                }
            } else if (urlParams.get('batch') === '1') {
                openBatchModal();
                batchForm.value.rawUrls = "https://example.com\nhttps://demo.org\napi.service.cn\n# 自动忽略注释与去重";
            }

            // Polling task status every 4 seconds when in dashboard
            tasksPollInterval = setInterval(() => {
                if (currentView.value === 'tasks') {
                    loadTasks();
                    loadGlobalDomainStats();
                } else if (currentView.value === 'global_domains') {
                    loadGlobalDomainStats();
                }
            }, 4000);
        });

        onUnmounted(() => {
            if (tasksPollInterval) clearInterval(tasksPollInterval);
            closeEventSource();
        });

        return {
            currentView,
            activeTab,
            tasks,
            activeTask,
            runningTasksCount,
            totalPagesCrawled,
            totalExtDomainsFound,
            totalSubdomainsFound,
            showCreateModal,
            showAdvanced,
            showEvidenceModal,
            selectedDomainForEvidence,
            domainOccurrences,
            newTask,
            showBatchModal,
            showBatchAdvanced,
            isBatchSubmitting,
            batchFileInput,
            batchForm,
            parsedBatchUrls,
            selectedTaskIds,
            deletingTaskIds,
            isBatchOperating,
            currentBatchAction,
            isAllSelected,
            openBatchModal,
            handleBatchFileUpload,
            submitBatchImport,
            toggleSelectAll,
            executeBatchAction,
            domainsList,
            domainsTotal,
            domainPage,
            domainFilters,
            domainStats,
            selectedDomains,
            isAllDomainsSelected,
            toggleSelectAllDomains,
            showTagModal,
            tagTargetDomain,
            tagForm,
            openTagModal,
            toggleTag,
            addCustomTag,
            saveTagForm,
            showVerifyModal,
            verifyVerdict,
            verifyTargetDomain,
            verifyingMap,
            batchVerifying,
            evaluatingRules,
            verifySingleDomain,
            showVerifyReport,
            batchVerifySelected,
            batchSetRisk,
            evaluateRulesForTask,
            filterByRisk,
            filterByVerify,
            filterGlobalByRisk,
            filterGlobalByVerify,
            showRiskProfilesModal,
            riskProfiles,
            riskProfilesTotal,
            riskProfilePage,
            riskProfileSearch,
            riskProfileLevelFilter,
            showAddProfileForm,
            showBatchImportProfilesForm,
            batchImportProfilesText,
            isImportingProfiles,
            isSyncingHistory,
            newProfile,
            openRiskProfilesModal,
            loadRiskProfiles,
            submitAddProfile,
            deleteRiskProfile,
            submitBatchImportProfiles,
            syncAllProfilesToHistory,
            globalDomainsList,
            globalDomainsTotal,
            globalDomainPage,
            globalDomainFilters,
            globalDomainStats,
            showAssociatedTasksModal,
            selectedDomainForTasks,
            associatedTasksList,
            isLoadingAssociatedTasks,
            switchView,
            loadGlobalDomains,
            loadGlobalDomainStats,
            openAssociatedTasksModal,
            jumpToTaskDetail,
            subdomainsList,
            subdomainsTotal,
            subdomainPage,
            subdomainFilters,
            subdomainStats,
            sitemapPages,
            sitemapTotal,
            sitemapPage,
            sitemapFilters,
            logs,
            autoScrollLogs,
            terminalRef,
            liveProgress,
            loadTasks,
            openCreateModal,
            submitCreateTask,
            enterTask,
            startTask,
            pauseTask,
            resumeTask,
            stopTask,
            retryTask,
            deleteTask,
            cleaningDomains,
            cleanDomains,
            loadDomains,
            loadSubdomains,
            loadSubdomainStats,
            loadSitemap,
            openEvidenceModal,
            clearLogs,
            getProgressPercent,
            getStatusLabel,
            getStatusBadgeClass,
            getLogLevelClass
        };
    }
});

app.mount('#app');
