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
                concurrency: 35,
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

        // ==================== Risk Page Remediation State ====================
        const remediationPages = ref([]);
        const remediationTotal = ref(0);
        const remediationPage = ref(1);
        const remediationPageSize = ref(50);
        const remediationLoading = ref(false);
        const remediationStats = ref({
            total_items: 0,
            pending_count: 0,
            failed_count: 0,
            unverified_count: 0,
            clean_count: 0,
            tasks_affected: 0,
            unique_risk_domains: 0,
            unique_pages: 0,
            level_counts: { critical: 0, high: 0, medium: 0, low: 0 },
            task_summary: []
        });
        const remediationFilters = ref({
            taskId: '',
            riskLevel: '',
            verifyStatus: 'pending_only',
            manualStatus: '',
            search: ''
        });
        const remediationTimer = ref({
            is_running: true,
            is_checking: false,
            interval_seconds: 10800,
            remaining_seconds: 10800,
            last_run_time: null,
            next_run_time: null,
            last_run_stats: {}
        });
        const selectedRemediationIds = ref([]);
        const isAllRemediationSelected = computed(() => {
            if (!remediationPages.value.length) return false;
            return remediationPages.value.every(p => selectedRemediationIds.value.includes(p.id));
        });
        const verifyingPageId = ref(null);
        const isTriggeringBatchVerify = ref(false);
        const isSyncingOccurrences = ref(false);

        // Modals for risk remediation
        const showExportModal = ref(false);
        const exportForm = ref({
            taskId: '',
            verifyStatus: 'pending_only',
            riskLevel: ''
        });
        const showGuideModal = ref(false);
        const selectedGuideItem = ref(null);

        // New Task Form
        const newTask = ref({
            name: '',
            target_url: '',
            config: {
                max_depth: 10,
                max_pages: 1000,
                concurrency: 35,
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

        // Global External Domains Assessment Modal State
        const showGlobalAssessModal = ref(false);
        const globalAssessTarget = ref(null);
        const savingGlobalAssess = ref(false);
        const globalAssessForm = ref({
            rule_type: 'root',
            target_domain: '',
            risk_level: 'high',
            tags: [],
            customTag: '',
            remark: '',
            sync_to_history: true
        });

        // Targeted Verification Modal State & Loading Maps
        const showVerifyModal = ref(false);
        const verifyVerdict = ref(null);
        const verifyTargetDomain = ref('');
        const verifyingMap = ref({});
        const batchVerifying = ref(false);
        const evaluatingRules = ref(false);

        // Evidence & Global Modal Verification State
        const selectedDomainEvidenceItem = ref(null);
        const isVerifyingModalEvidence = ref(false);
        const selectedDomainForTasksItem = ref(null);
        const isVerifyingGlobalTasks = ref(false);

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


        const isRiskDomain = (level) => {
            if (!level) return false;
            const l = String(level).toLowerCase().trim();
            return ['critical', 'high', 'medium', 'low'].includes(l);
        };

        const getRiskBadgeClass = (level) => {
            const map = {
                critical: 'bg-rose-950 text-rose-300 border-rose-800/80 font-bold',
                high: 'bg-red-950 text-red-300 border-red-800/80 font-semibold',
                medium: 'bg-amber-950 text-amber-300 border-amber-800/80 font-semibold',
                low: 'bg-blue-950 text-blue-300 border-blue-800/80',
                safe: 'bg-emerald-950 text-emerald-300 border-emerald-800/80',
                pending: 'bg-slate-800 text-slate-400 border-slate-700'
            };
            return map[level] || 'bg-slate-800 text-slate-400 border-slate-700';
        };

        const getRiskLevelLabel = (level) => {
            const map = {
                critical: '🔴 严重',
                high: '🔴 高危',
                medium: '🟡 中危',
                low: '🔵 低危',
                safe: '🟢 安全',
                pending: '⚪ 待研判'
            };
            return map[level] || '⚪ 待研判';
        };

        const openEvidenceModal = async (domain, domainItem = null) => {
            if (!activeTask.value) return;
            selectedDomainForEvidence.value = domain;
            if (domainItem) {
                selectedDomainEvidenceItem.value = domainItem;
            } else {
                selectedDomainEvidenceItem.value = domainsList.value.find(d => d.domain === domain) || null;
            }
            domainOccurrences.value = [];
            showEvidenceModal.value = true;

            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/${encodeURIComponent(domain)}/occurrences?limit=50`);
                if (res.ok) {
                    const data = await res.json();
                    domainOccurrences.value = (data.occurrences || []).map(o => ({
                        ...o,
                        _verifying: false,
                        verify_status: null
                    }));
                }
            } catch (e) {
                console.error(e);
            }
        };

        const verifySingleOccurrence = async (occ) => {
            if (!activeTask.value || !selectedDomainForEvidence.value || !occ.page_url) return;
            occ._verifying = true;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/${encodeURIComponent(selectedDomainForEvidence.value)}/verify-page?url=${encodeURIComponent(occ.page_url)}`, {
                    method: 'POST'
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.result) {
                        occ.verify_status = data.result.status;
                    }
                } else {
                    let errMsg = "复测失败";
                    try { const err = await res.json(); errMsg = err.detail || JSON.stringify(err); } catch {}
                    alert("复测失败: " + errMsg);
                }
            } catch (e) {
                alert("复测异常: " + e.message);
            } finally {
                occ._verifying = false;
            }
        };

        const verifyAllModalOccurrences = async () => {
            if (!activeTask.value || !selectedDomainForEvidence.value) return;
            isVerifyingModalEvidence.value = true;
            try {
                const res = await fetch(`/api/tasks/${activeTask.value.id}/domains/${encodeURIComponent(selectedDomainForEvidence.value)}/verify`, {
                    method: 'POST'
                });
                if (res.ok) {
                    const data = await res.json();
                    const verdict = data.verdict;
                    if (verdict && Array.isArray(verdict.details)) {
                        const detailMap = {};
                        verdict.details.forEach(d => {
                            if (d.url) detailMap[d.url] = d.status;
                        });
                        domainOccurrences.value.forEach(occ => {
                            if (detailMap[occ.page_url]) {
                                occ.verify_status = detailMap[occ.page_url];
                            } else if (verdict.verify_status === 'verified_clean') {
                                occ.verify_status = 'domain_cleared';
                            }
                        });
                    }
                    const item = domainsList.value.find(d => d.domain === selectedDomainForEvidence.value);
                    if (item && verdict) {
                        item.verify_status = verdict.verify_status;
                        item.verify_time = verdict.verify_time;
                        item.verify_detail = JSON.stringify(verdict);
                    }
                    await loadDomainStats();
                    showVerifyReport(verdict, selectedDomainForEvidence.value);
                } else {
                    let errMsg = "一键复测失败";
                    try { const err = await res.json(); errMsg = err.detail || JSON.stringify(err); } catch {}
                    alert("一键复测失败: " + errMsg);
                }
            } catch (e) {
                alert("一键复测异常: " + e.message);
            } finally {
                isVerifyingModalEvidence.value = false;
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
            } else if (viewName === 'risk_remediation') {
                url.searchParams.set('view', 'risk_remediation');
                url.searchParams.delete('task_id');
                loadRemediationPages(1);
                loadRemediationStats();
                loadTimerStatus();
            } else if (viewName === 'tasks') {
                url.searchParams.delete('view');
                url.searchParams.delete('task_id');
                loadTasks();
                loadGlobalDomainStats();
                loadRemediationStats();
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

        const openAssociatedTasksModal = async (domain, domainItem = null) => {
            selectedDomainForTasks.value = domain;
            if (domainItem) {
                selectedDomainForTasksItem.value = domainItem;
            } else {
                selectedDomainForTasksItem.value = globalDomainsList.value.find(d => d.domain === domain) || null;
            }
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

        const verifyGlobalAssociatedTasks = async () => {
            if (!selectedDomainForTasks.value) return;
            isVerifyingGlobalTasks.value = true;
            try {
                const res = await fetch(`/api/global-domains/${encodeURIComponent(selectedDomainForTasks.value)}/verify`, {
                    method: 'POST'
                });
                if (res.ok) {
                    const data = await res.json();
                    if (Array.isArray(data.tasks)) {
                        const taskResultMap = {};
                        data.tasks.forEach(t => {
                            taskResultMap[t.task_id] = t;
                        });
                        associatedTasksList.value.forEach(t => {
                            const match = taskResultMap[t.task_id];
                            if (match) {
                                t.verify_progress = match.progress_text;
                                t.verify_status = match.verify_status;
                                t.verify_time = match.verify_time;
                            }
                        });
                    }
                    await loadGlobalDomains(globalDomainPage.value);
                    await loadGlobalDomainStats();
                    alert(`全库复测完成！已核验 ${data.task_count || associatedTasksList.value.length} 个扫描任务的闭环修复情况。`);
                } else {
                    let errMsg = "全库复测失败";
                    try { const err = await res.json(); errMsg = err.detail || JSON.stringify(err); } catch {}
                    alert("全库复测失败: " + errMsg);
                }
            } catch (e) {
                alert("全库复测异常: " + e.message);
            } finally {
                isVerifyingGlobalTasks.value = false;
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

        // ==================== Risk Page Remediation Methods ====================
        const loadRemediationPages = async (page = 1) => {
            remediationPage.value = page;
            remediationLoading.value = true;
            try {
                const params = new URLSearchParams({
                    page: page,
                    page_size: remediationPageSize.value
                });
                if (remediationFilters.value.taskId) {
                    params.append('task_id', remediationFilters.value.taskId);
                }
                if (remediationFilters.value.riskLevel) {
                    params.append('risk_level', remediationFilters.value.riskLevel);
                }
                if (remediationFilters.value.verifyStatus) {
                    params.append('verify_status', remediationFilters.value.verifyStatus);
                }
                if (remediationFilters.value.manualStatus) {
                    params.append('manual_status', remediationFilters.value.manualStatus);
                }
                if (remediationFilters.value.search && remediationFilters.value.search.trim()) {
                    params.append('search', remediationFilters.value.search.trim());
                }

                const res = await fetch(`/api/risk-remediation/pages?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    remediationPages.value = data.items || [];
                    remediationTotal.value = data.total || 0;
                }
            } catch (e) {
                console.error("Failed to load remediation pages:", e);
            } finally {
                remediationLoading.value = false;
            }
        };

        const loadRemediationStats = async () => {
            try {
                const res = await fetch('/api/risk-remediation/stats');
                if (res.ok) {
                    remediationStats.value = await res.json();
                }
            } catch (e) {
                console.error("Failed to load remediation stats:", e);
            }
        };

        const loadTimerStatus = async () => {
            try {
                const res = await fetch('/api/risk-remediation/timer-status');
                if (res.ok) {
                    const data = await res.json();
                    remediationTimer.value = data;
                }
            } catch (e) {
                console.error("Failed to load timer status:", e);
            }
        };

        const verifySingleRemediationPage = async (item) => {
            if (verifyingPageId.value !== null) return;
            verifyingPageId.value = item.id;
            try {
                const res = await fetch(`/api/risk-remediation/${item.id}/verify`, { method: 'POST' });
                if (res.ok) {
                    const result = await res.json();
                    item.verify_status = result.verify_status;
                    item.last_verified_at = result.verify_time;
                    item.last_verify_detail = result.verify_detail;
                    await loadRemediationStats();
                } else {
                    alert("复测请求失败");
                }
            } catch (e) {
                alert("复测请求异常: " + e.message);
            } finally {
                verifyingPageId.value = null;
            }
        };

        const triggerBatchVerify = async () => {
            if (isTriggeringBatchVerify.value) return;
            isTriggeringBatchVerify.value = true;
            try {
                const res = await fetch('/api/risk-remediation/trigger-verify', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    alert(data.message || "已触发全量待复测风险页面校验！后台正在异步并发核验中。");
                    await loadTimerStatus();
                    setTimeout(() => {
                        loadRemediationPages(remediationPage.value);
                        loadRemediationStats();
                    }, 2000);
                }
            } catch (e) {
                alert("触发复测异常: " + e.message);
            } finally {
                isTriggeringBatchVerify.value = false;
            }
        };

        const syncRemediationOccurrences = async () => {
            if (isSyncingOccurrences.value) return;
            isSyncingOccurrences.value = true;
            try {
                const res = await fetch('/api/risk-remediation/sync', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    alert(`同步完成！共检查 ${data.risk_domains_checked || 0} 个风险域名，提取并对齐了 ${data.synced_count || 0} 条风险页面存证。`);
                    await loadRemediationPages(1);
                    await loadRemediationStats();
                }
            } catch (e) {
                alert("同步风险数据异常: " + e.message);
            } finally {
                isSyncingOccurrences.value = false;
            }
        };

        const batchUpdateManualStatus = async (status) => {
            if (!selectedRemediationIds.value.length) return;
            try {
                const res = await fetch('/api/risk-remediation/batch-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ids: selectedRemediationIds.value,
                        manual_status: status
                    })
                });
                if (res.ok) {
                    selectedRemediationIds.value = [];
                    await loadRemediationPages(remediationPage.value);
                    await loadRemediationStats();
                }
            } catch (e) {
                alert("批量修改状态失败: " + e.message);
            }
        };

        const toggleSelectAllRemediation = () => {
            if (isAllRemediationSelected.value) {
                selectedRemediationIds.value = [];
            } else {
                selectedRemediationIds.value = remediationPages.value.map(p => p.id);
            }
        };

        const openExportModal = () => {
            exportForm.value.taskId = remediationFilters.value.taskId || '';
            exportForm.value.verifyStatus = remediationFilters.value.verifyStatus || 'pending_only';
            exportForm.value.riskLevel = remediationFilters.value.riskLevel || '';
            showExportModal.value = true;
        };

        const executeExport = () => {
            const params = new URLSearchParams();
            if (exportForm.value.taskId) params.append('task_id', exportForm.value.taskId);
            if (exportForm.value.verifyStatus) params.append('verify_status', exportForm.value.verifyStatus);
            if (exportForm.value.riskLevel) params.append('risk_level', exportForm.value.riskLevel);
            const exportUrl = `/api/risk-remediation/export?${params.toString()}`;
            window.open(exportUrl, '_blank');
            showExportModal.value = false;
        };

        const openGuideModal = (item) => {
            selectedGuideItem.value = item;
            showGuideModal.value = true;
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

        // Global Domain Assessment & Rule Creation
        const openGlobalAssessModal = (domainItem) => {
            if (!domainItem) return;
            globalAssessTarget.value = domainItem;
            const defaultTarget = domainItem.root_domain || domainItem.domain;
            globalAssessForm.value = {
                rule_type: 'root',
                target_domain: defaultTarget,
                risk_level: domainItem.risk_level && domainItem.risk_level !== 'pending' ? domainItem.risk_level : 'high',
                tags: Array.isArray(domainItem.risk_tags) ? [...domainItem.risk_tags] : [],
                customTag: '',
                remark: domainItem.risk_remark || '',
                sync_to_history: true
            };
            showGlobalAssessModal.value = true;
        };

        const onGlobalAssessTypeChange = () => {
            if (!globalAssessTarget.value) return;
            if (globalAssessForm.value.rule_type === 'root') {
                globalAssessForm.value.target_domain = globalAssessTarget.value.root_domain || globalAssessTarget.value.domain;
            } else {
                globalAssessForm.value.target_domain = globalAssessTarget.value.domain;
            }
        };

        const toggleGlobalAssessTag = (tagName) => {
            const idx = globalAssessForm.value.tags.indexOf(tagName);
            if (idx >= 0) {
                globalAssessForm.value.tags.splice(idx, 1);
            } else {
                globalAssessForm.value.tags.push(tagName);
            }
        };

        const addGlobalAssessCustomTag = () => {
            const t = (globalAssessForm.value.customTag || '').trim();
            if (t && !globalAssessForm.value.tags.includes(t)) {
                globalAssessForm.value.tags.push(t);
                globalAssessForm.value.customTag = '';
            }
        };

        const saveGlobalAssessForm = async () => {
            if (!globalAssessTarget.value || !globalAssessForm.value.target_domain.trim()) {
                alert("规则目标域名不能为空");
                return;
            }
            savingGlobalAssess.value = true;
            try {
                const payload = {
                    domain: globalAssessForm.value.target_domain.trim(),
                    match_type: globalAssessForm.value.rule_type,
                    risk_level: globalAssessForm.value.risk_level,
                    category: globalAssessForm.value.tags[0] || "",
                    tags: globalAssessForm.value.tags,
                    remark: globalAssessForm.value.remark.trim(),
                    sync_to_history: Boolean(globalAssessForm.value.sync_to_history)
                };
                const res = await fetch('/api/risk-profiles', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    showGlobalAssessModal.value = false;
                    await loadGlobalDomains(globalDomainPage.value);
                    await loadGlobalDomainStats();
                    const modeDesc = payload.match_type === 'root' ? `*.${payload.domain}` : payload.domain;
                    alert(`研判情报规则已成功创建并生效！\n规则目标: ${modeDesc}\n风险级别: ${payload.risk_level}${payload.sync_to_history ? '\n已自动回溯同步全系统历史任务。' : ''}`);
                } else {
                    let errMsg = "未知错误";
                    try {
                        const err = await res.json();
                        errMsg = err.detail || JSON.stringify(err);
                    } catch {
                        errMsg = await res.text() || res.statusText;
                    }
                    alert("保存研判规则失败: " + errMsg);
                }
            } catch (e) {
                alert("保存研判规则异常: " + e.message);
            } finally {
                savingGlobalAssess.value = false;
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
                    let errMsg = "未知错误";
                    try {
                        const err = await res.json();
                        errMsg = err.detail || JSON.stringify(err);
                    } catch {
                        errMsg = (await res.text()) || res.statusText || `HTTP ${res.status}`;
                    }
                    alert("复测请求失败: " + errMsg);
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
                    let errMsg = "批量复测失败";
                    try {
                        const err = await res.json();
                        errMsg = err.detail || JSON.stringify(err);
                    } catch {
                        errMsg = (await res.text()) || res.statusText || `HTTP ${res.status}`;
                    }
                    alert("批量复测失败: " + errMsg);
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

        const handleProfileFileUpload = (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (event) => {
                batchImportProfilesText.value = event.target.result || '';
            };
            reader.readAsText(file);
            e.target.value = '';
        };

        const submitBatchImportProfiles = async () => {
            const raw = (batchImportProfilesText.value || '').trim();
            if (!raw) {
                alert("请输入或选择要导入的情报规则内容");
                return;
            }
            isImportingProfiles.value = true;
            try {
                const lines = raw.split('\n');
                const items = [];
                for (const line of lines) {
                    const l = line.trim();
                    if (!l || l.startsWith('#')) continue;
                    const parts = l.split(/[,，\t]/).map(p => p.trim());
                    const rawDom = parts[0] || '';
                    if (!rawDom) continue;

                    const isWildcard = rawDom.startsWith('*.');
                    const matchType = isWildcard ? 'root' : 'exact';

                    // 规范化风险级别
                    let level = (parts[1] || 'high').toLowerCase();
                    if (level.includes('严重') || level === 'critical') level = 'critical';
                    else if (level.includes('高危') || level === 'high') level = 'high';
                    else if (level.includes('中危') || level === 'medium') level = 'medium';
                    else if (level.includes('低危') || level === 'low') level = 'low';
                    else if (level.includes('安全') || level.includes('白名单') || level === 'safe') level = 'safe';
                    else if (level.includes('待研判') || level === 'pending') level = 'pending';
                    else level = 'high';

                    const category = parts[2] || '';

                    // 标签解析: 第4列(以/或;分隔)
                    let tags = [];
                    if (parts[3]) {
                        tags = parts[3].split(/[\/；;、\s]+/).map(t => t.trim()).filter(Boolean);
                    }
                    if (tags.length === 0 && category) {
                        tags = [category];
                    }

                    // 备注说明: 第5列及后续内容
                    let remark = '';
                    if (parts.length > 4) {
                        remark = parts.slice(4).join('，').trim();
                    } else if (parts[3] && tags.length === 0) {
                        remark = parts[3];
                    } else {
                        remark = category ? `批量导入: ${category}` : '批量导入情报';
                    }

                    items.push({
                        domain: rawDom,
                        match_type: matchType,
                        risk_level: level,
                        category: category,
                        tags: tags,
                        remark: remark,
                        sync_to_history: true
                    });
                }

                if (items.length === 0) {
                    alert("未识别到有效的规则内容，请检查格式后重试（每行一条: 域名,风险等级,分类,标签,备注）");
                    return;
                }

                const res = await fetch('/api/risk-profiles/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items, sync_to_history: true })
                });
                if (res.ok) {
                    const data = await res.json();
                    alert(`导入成功！共导入 ${data.imported_count} 条风险情报规则并完成历史回溯！`);
                    batchImportProfilesText.value = '';
                    showBatchImportProfilesForm.value = false;
                    await loadRiskProfiles(1);
                    if (activeTask.value) {
                        await loadDomains(1);
                        await loadDomainStats();
                    }
                    await loadGlobalDomainStats();
                } else {
                    const err = await res.text();
                    alert("批量导入失败: " + err);
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

        let timerCountdownInterval = null;

        // Lifecycle Hooks
        onMounted(async () => {
            await loadTasks();
            await loadGlobalDomainStats();
            await loadRemediationStats();

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
            } else if (viewParam === 'risk_remediation') {
                currentView.value = 'risk_remediation';
                await loadRemediationPages(1);
                await loadRemediationStats();
                await loadTimerStatus();
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

            // 1-second countdown for risk remediation scheduler
            timerCountdownInterval = setInterval(() => {
                if (remediationTimer.value && remediationTimer.value.remaining_seconds > 0) {
                    remediationTimer.value.remaining_seconds--;
                    if (remediationTimer.value.remaining_seconds <= 0) {
                        loadTimerStatus();
                        if (currentView.value === 'risk_remediation') {
                            loadRemediationPages(remediationPage.value);
                            loadRemediationStats();
                        }
                    }
                }
            }, 1000);

            // Polling task status every 4 seconds when in dashboard
            tasksPollInterval = setInterval(() => {
                if (currentView.value === 'tasks') {
                    loadTasks();
                    loadGlobalDomainStats();
                    loadRemediationStats();
                } else if (currentView.value === 'global_domains') {
                    loadGlobalDomainStats();
                } else if (currentView.value === 'risk_remediation') {
                    loadTimerStatus();
                }
            }, 4000);
        });

        onUnmounted(() => {
            if (tasksPollInterval) clearInterval(tasksPollInterval);
            if (timerCountdownInterval) clearInterval(timerCountdownInterval);
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
            isRiskDomain,
            getRiskBadgeClass,
            getRiskLevelLabel,
            selectedDomainEvidenceItem,
            isVerifyingModalEvidence,
            selectedDomainForTasksItem,
            isVerifyingGlobalTasks,
            verifySingleOccurrence,
            verifyAllModalOccurrences,
            verifyGlobalAssociatedTasks,
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
            handleProfileFileUpload,
            submitBatchImportProfiles,
            syncAllProfilesToHistory,
            globalDomainsList,
            globalDomainsTotal,
            globalDomainPage,
            globalDomainFilters,
            globalDomainStats,
            showGlobalAssessModal,
            globalAssessTarget,
            savingGlobalAssess,
            globalAssessForm,
            openGlobalAssessModal,
            onGlobalAssessTypeChange,
            toggleGlobalAssessTag,
            addGlobalAssessCustomTag,
            saveGlobalAssessForm,
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
            getLogLevelClass,
            remediationPages,
            remediationTotal,
            remediationPage,
            remediationPageSize,
            remediationLoading,
            remediationStats,
            remediationFilters,
            remediationTimer,
            selectedRemediationIds,
            isAllRemediationSelected,
            verifyingPageId,
            isTriggeringBatchVerify,
            isSyncingOccurrences,
            showExportModal,
            exportForm,
            showGuideModal,
            selectedGuideItem,
            loadRemediationPages,
            loadRemediationStats,
            loadTimerStatus,
            verifySingleRemediationPage,
            triggerBatchVerify,
            syncRemediationOccurrences,
            batchUpdateManualStatus,
            toggleSelectAllRemediation,
            openExportModal,
            executeExport,
            openGuideModal
        };
    }
});

app.mount('#app');
