import { useI18n } from '../i18n';
import { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  ChevronLeft, 
  ChevronRight, 
  CheckSquare, 
  Square, 
  Check, 
  AlertCircle, 
  ArrowDownWideNarrow, 
  ArrowUpNarrowWide, 
  FolderDown, 
  SlidersHorizontal,
  UploadCloud,
  X,
  Layers,
  Video,
  Image as ImageIcon,
  Bookmark,
  Heart,
  FolderCheck,
  RotateCcw
} from 'lucide-react';
import { useLocation } from 'react-router-dom';
import MediaCard from '../components/MediaCard';
import type { Post, CustomCategory } from '../components/MediaCard';
import Inspector from '../components/Inspector';

const API_BASE = 'http://127.0.0.1:8000';

const Library = () => {
  const { t, language } = useI18n();
  const location = useLocation();

  const [posts, setPosts] = useState<Post[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [customCategories, setCustomCategories] = useState<CustomCategory[]>([]);
  const [creators, setCreators] = useState<string[]>([]);
  const [collections, setCollections] = useState<{ name: string; count: number }[]>([]);

  // Search & Filters
  const [search, setSearch] = useState('');
  const queryParams = new URLSearchParams(location.search);
  const [categoryFilter, setCategoryFilter] = useState(queryParams.get('category') || '');
  const [customCategoryFilter, setCustomCategoryFilter] = useState(queryParams.get('custom_category_id') || '');
  const [statusFilter, setStatusFilter] = useState(queryParams.get('status') || '');
  const [creatorFilter, setCreatorFilter] = useState('');
  const [formatFilter, setFormatFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState(queryParams.get('source') || '');
  const [collectionFilter, setCollectionFilter] = useState(queryParams.get('collection') || '');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  // UI States
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [dragImportLoading, setDragImportLoading] = useState(false);

  // Sorting
  const [sortBy, setSortBy] = useState('activity_date');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [totalCount, setTotalCount] = useState(0);

  // Selection & Bulk Actions
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [selectedPks, setSelectedPks] = useState<Set<string>>(new Set());
  const [bulkCategoryTarget, setBulkCategoryTarget] = useState<string>('');
  const [bulkActionMessage, setBulkActionMessage] = useState('');
  const [bulkActionError, setBulkActionError] = useState('');

  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [importMessage, setImportMessage] = useState('');
  const [loadError, setLoadError] = useState('');
  const requestId = useRef(0);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const cat = params.get('category') || '';
    const customCat = params.get('custom_category_id') || '';
    const col = params.get('collection') || '';
    const st = params.get('status') || '';
    const src = params.get('source') || '';
    setCategoryFilter(cat);
    setCustomCategoryFilter(customCat);
    setCollectionFilter(col);
    if (st) setStatusFilter(st);
    if (src) setSourceFilter(src);
    setCurrentPage(1);
  }, [location.search]);

  const fetchCategories = async () => {
    try {
      const res = await fetch(`${API_BASE}/categories`);
      if (res.ok) setCategories(await res.json());
    } catch (e) {
      console.error('Failed to fetch categories', e);
    }
  };

  const fetchCustomCategories = async () => {
    try {
      const res = await fetch(`${API_BASE}/custom-categories`);
      if (res.ok) setCustomCategories(await res.json());
    } catch (e) {
      console.error('Failed to fetch custom categories', e);
    }
  };

  useEffect(() => {
    fetchCategories();
    fetchCustomCategories();
    fetch(`${API_BASE}/facets`).then(res => res.json()).then(data => setCreators(data.creators || [])).catch(() => {});
    fetch(`${API_BASE}/import/export/collections`).then(res => res.json()).then(setCollections).catch(() => {});
  }, []);

  const fetchPosts = async (page = currentPage, limit = pageSize) => {
    const thisRequest = ++requestId.current;
    try {
      const offset = (page - 1) * limit;
      const params = new URLSearchParams();
      if (search.trim()) params.append('search', search.trim());
      if (categoryFilter) params.append('category', categoryFilter);
      if (customCategoryFilter) params.append('custom_category_id', customCategoryFilter);
      if (statusFilter) params.append('status', statusFilter);
      if (creatorFilter) params.append('creator', creatorFilter);
      if (formatFilter) params.append('media_type', formatFilter);
      if (sourceFilter) params.append('source', sourceFilter);
      if (collectionFilter) params.append('collection', collectionFilter);
      if (fromDate) params.append('from_date', fromDate);
      if (toDate) params.append('to_date', toDate);
      if (sortBy) params.append('sort_by', sortBy);
      if (sortOrder) params.append('sort_order', sortOrder);
      params.append('limit', String(limit));
      params.append('offset', String(offset));

      const res = await fetch(`${API_BASE}/posts?${params.toString()}`);
      if (!res.ok) throw new Error((await res.json()).detail || 'Could not load library');

      const data = await res.json();
      if (thisRequest !== requestId.current) return;

      const totalHeader = res.headers.get('X-Total-Count');
      if (totalHeader) {
        setTotalCount(parseInt(totalHeader, 10));
      } else {
        setTotalCount(data.length);
      }

      setLoadError('');
      setPosts(data);
      setCurrentPage(page);
    } catch (e) {
      setLoadError(String(e));
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPosts(1, pageSize);
    }, 300); // debounce
    return () => clearTimeout(timer);
  }, [search, categoryFilter, customCategoryFilter, statusFilter, creatorFilter, formatFilter, sourceFilter, collectionFilter, fromDate, toDate, sortBy, sortOrder, pageSize]);

  const handlePageChange = (newPage: number) => {
    const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
    if (newPage < 1 || newPage > totalPages) return;
    fetchPosts(newPage, pageSize);
    const gridElem = document.querySelector('.media-grid');
    if (gridElem) gridElem.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const importMedia = async () => {
    try {
      const bridge = (window as Window & { appBridge?: { importMedia: () => Promise<number> } }).appBridge;
      if (!bridge) throw new Error('Local import is available in the desktop app');
      const count = await bridge.importMedia();
      if (count) {
        setImportMessage(`${count} ${t("فایل محلی با موفقیت وارد شد.")}`);
        fetchPosts(1, pageSize);
        setTimeout(() => setImportMessage(''), 4000);
      }
    } catch (error: any) {
      setImportMessage(error.message || String(error));
      setTimeout(() => setImportMessage(''), 5000);
    }
  };

  // Drag and Drop files directly from Windows Explorer into Library
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDraggingOver) setIsDraggingOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDraggingOver(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);

    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;

    setDragImportLoading(true);
    let successCount = 0;
    const errors: string[] = [];

    const bridge = (window as any).appBridge;
    for (const file of files) {
      const filePath = (file as any).path;
      if (!filePath) continue;

      try {
        if (bridge?.importFilePath) {
          await bridge.importFilePath(filePath);
          successCount++;
        } else {
          const res = await fetch(`${API_BASE}/import/local`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath })
          });
          if (res.ok) successCount++;
          else {
            const err = await res.json().catch(() => ({}));
            errors.push(err.detail || file.name);
          }
        }
      } catch (err: any) {
        errors.push(err.message || file.name);
      }
    }

    setDragImportLoading(false);
    if (successCount > 0) {
      setImportMessage(`${successCount} ${t("فایل با موفقیت به کتابخانه افزوده شد.")}`);
      fetchPosts(1, pageSize);
      setTimeout(() => setImportMessage(''), 4500);
    }
    if (errors.length > 0) {
      setLoadError(`${t("خطا در واردسازی:")} ${errors.join(', ')}`);
      setTimeout(() => setLoadError(''), 6000);
    }
  };

  const handleSaveMetadata = async (pk: string, data: any) => {
    try {
      const res = await fetch(`${API_BASE}/posts/${pk}/metadata`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Save failed');

      setPosts(prev => prev.map(p => {
        if (p.pk === pk) {
          const updatedCustomCats = data.custom_category_ids
            ? customCategories.filter(c => data.custom_category_ids.includes(c.id))
            : p.custom_categories;
          return {
            ...p,
            caption: data.caption !== undefined ? data.caption : p.caption,
            ai_category: data.category,
            ai_tags: data.tags,
            ai_summary: data.summary,
            custom_categories: updatedCustomCats,
            status: data.status || (p.status === 'ORGANIZED' ? 'APPROVED' : p.status)
          };
        }
        return p;
      }));

      if (selectedPost && selectedPost.pk === pk) {
        const updatedCustomCats = data.custom_category_ids
          ? customCategories.filter(c => data.custom_category_ids.includes(c.id))
          : selectedPost.custom_categories;
        setSelectedPost({
          ...selectedPost,
          caption: data.caption !== undefined ? data.caption : selectedPost.caption,
          ai_category: data.category,
          ai_tags: data.tags,
          ai_summary: data.summary,
          custom_categories: updatedCustomCats,
          status: data.status || (selectedPost.status === 'ORGANIZED' ? 'APPROVED' : selectedPost.status)
        });
      }
    } catch (e: any) {
      setLoadError(e.message || String(e));
      setTimeout(() => setLoadError(''), 5000);
    }
  };

  // Bulk Actions
  const handleToggleSelectPost = (post: Post, selected: boolean) => {
    setSelectedPks(prev => {
      const next = new Set(prev);
      if (selected) next.add(post.pk);
      else next.delete(post.pk);
      return next;
    });
  };

  const handleSelectAllOnPage = () => {
    if (selectedPks.size === posts.length && posts.length > 0) {
      setSelectedPks(new Set());
    } else {
      setSelectedPks(new Set(posts.map(p => p.pk)));
    }
  };

  const handleBulkAssign = async () => {
    if (!bulkCategoryTarget || selectedPks.size === 0) return;
    setBulkActionError('');
    setBulkActionMessage('');
    try {
      const res = await fetch(`${API_BASE}/custom-categories/${bulkCategoryTarget}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ post_pks: Array.from(selectedPks) })
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to assign category');
      const result = await res.json();
      const count = result.assigned_count ?? result.assigned ?? selectedPks.size;
      setBulkActionMessage(`${count} ${t("پست به دسته‌بندی افزوده شدند.")}`);
      fetchPosts(currentPage, pageSize);
      fetchCustomCategories();
      setTimeout(() => setBulkActionMessage(''), 3500);
    } catch (e: any) {
      setBulkActionError(e.message || String(e));
      setTimeout(() => setBulkActionError(''), 4000);
    }
  };

  const handleBulkRemove = async () => {
    if (!bulkCategoryTarget || selectedPks.size === 0) return;
    setBulkActionError('');
    setBulkActionMessage('');
    try {
      const res = await fetch(`${API_BASE}/custom-categories/${bulkCategoryTarget}/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ post_pks: Array.from(selectedPks) })
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to remove from category');
      const result = await res.json();
      const count = result.removed_count ?? result.removed ?? selectedPks.size;
      setBulkActionMessage(`${count} ${t("پست از دسته‌بندی خارج شدند.")}`);
      fetchPosts(currentPage, pageSize);
      fetchCustomCategories();
      setTimeout(() => setBulkActionMessage(''), 3500);
    } catch (e: any) {
      setBulkActionError(e.message || String(e));
      setTimeout(() => setBulkActionError(''), 4000);
    }
  };

  const handleBulkExport = async () => {
    if (selectedPks.size === 0) return;
    const bridge = (window as Window & { appBridge?: any }).appBridge;
    if (!bridge?.bulkExportMedia) {
      alert(t('خروجی بومی فایل‌ها در نسخه دسکتاپ فعال است.'));
      return;
    }
    const selectedPosts = posts.filter(p => selectedPks.has(p.pk));
    const allPaths = selectedPosts.flatMap(p => p.file_paths || []);
    if (allPaths.length === 0) {
      setBulkActionError(t('هیچ فایل دانلودشده‌ای برای پست‌های انتخاب‌شده یافت نشد.'));
      setTimeout(() => setBulkActionError(''), 4000);
      return;
    }
    try {
      setBulkActionError('');
      const res = await bridge.bulkExportMedia(allPaths);
      if (res && res.count !== undefined) {
        setBulkActionMessage(`${res.count} ${t("فایل با موفقیت در پوشهٔ انتخابی ذخیره شد.")}`);
        setTimeout(() => setBulkActionMessage(''), 4000);
      }
    } catch (e: any) {
      setBulkActionError(e.message || String(e));
      setTimeout(() => setBulkActionError(''), 4000);
    }
  };

  const hasActiveFilters = Boolean(
    search || 
    categoryFilter || 
    customCategoryFilter || 
    statusFilter || 
    creatorFilter || 
    formatFilter || 
    sourceFilter || 
    collectionFilter || 
    fromDate || 
    toDate
  );

  const clearAllFilters = () => {
    setSearch('');
    setCategoryFilter('');
    setCustomCategoryFilter('');
    setStatusFilter('');
    setCreatorFilter('');
    setFormatFilter('');
    setSourceFilter('');
    setCollectionFilter('');
    setFromDate('');
    setToDate('');
    setCurrentPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const startItem = totalCount > 0 ? (currentPage - 1) * pageSize + 1 : 0;
  const endItem = Math.min(currentPage * pageSize, totalCount);

  return (
    <div 
      className="library-container animate-fade-in"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Visual Drag and Drop Overlay */}
      {(isDraggingOver || dragImportLoading) && (
        <div className="library-drop-overlay">
          <UploadCloud size={60} color="#a855f7" className="animate-bounce" />
          <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 800, color: '#fff' }}>
            {dragImportLoading 
              ? t("در حال پردازش و واردسازی فایل‌ها...") 
              : t("فایل‌های ویدیو یا عکس را اینجا رها کنید")}
          </h2>
          <p style={{ margin: 0, color: '#cbd5e1', fontSize: '14px' }}>
            {dragImportLoading 
              ? t("لطفاً چند لحظه صبر کنید...") 
              : t("فایل‌ها به‌طور خودکار به کتابخانه افزوده شده و پوستر ویدیو تولید می‌شود.")}
          </p>
        </div>
      )}

      <div className="library-content">
        {/* Modern Top Header & Master Toolbar */}
        <header className="library-header-bar">
          <div className="library-header-main">
            <div className="library-title-group">
              <h1 className="library-page-title">{t("کتابخانه رسانه‌ها")}</h1>
              <span className="library-counter-pill">
                {language === 'fa' ? `${totalCount.toLocaleString('fa-IR')} پست` : `${totalCount.toLocaleString('en-US')} posts`}
              </span>
            </div>

            {/* Quick Actions */}
            <div className="library-header-actions">
              <button 
                type="button"
                className="btn btn-primary btn-import-glow"
                onClick={importMedia}
                title={t("افزودن ویدیو یا عکس از سیستم به کتابخانه")}
              >
                <UploadCloud size={16} />
                <span>{t("افزودن فایل محلی")}</span>
              </button>

              <button
                type="button"
                className={`btn ${isSelectMode ? 'btn-select-active' : ''}`}
                onClick={() => {
                  setIsSelectMode(!isSelectMode);
                  if (isSelectMode) setSelectedPks(new Set());
                }}
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                {isSelectMode ? <CheckSquare size={16} color="var(--primary)" /> : <Square size={16} />}
                <span>{isSelectMode ? t("لغو انتخاب چندتایی") : t("انتخاب چندتایی")}</span>
                {selectedPks.size > 0 && (
                  <span className="badge-count">{selectedPks.size}</span>
                )}
              </button>
            </div>
          </div>

          {/* Secondary Controls: Search, Quick Chips, Sort */}
          <div className="library-controls-row">
            {/* Search Input Box */}
            <div className="library-search-wrapper">
              <Search size={16} className="search-icon-inside" />
              <input 
                type="text" 
                className="library-search-input" 
                placeholder={t("جستجو در کپشن، تگ‌ها، منتشرکننده، متن صوت...")} 
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button 
                  type="button" 
                  className="search-clear-btn" 
                  onClick={() => setSearch('')}
                  title={t("پاک کردن")}
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Quick Filter Chips */}
            <div className="quick-chips-scroll">
              <button
                type="button"
                className={`quick-chip ${!formatFilter && !statusFilter && !sourceFilter ? 'active' : ''}`}
                onClick={() => {
                  setFormatFilter('');
                  setStatusFilter('');
                  setSourceFilter('');
                  setCurrentPage(1);
                }}
              >
                {t("همه")}
              </button>

              <button
                type="button"
                className={`quick-chip ${formatFilter === '2' ? 'active' : ''}`}
                onClick={() => {
                  setFormatFilter(formatFilter === '2' ? '' : '2');
                  setCurrentPage(1);
                }}
              >
                <Video size={13} />
                <span>{t("ویدیوها")}</span>
              </button>

              <button
                type="button"
                className={`quick-chip ${formatFilter === '1' ? 'active' : ''}`}
                onClick={() => {
                  setFormatFilter(formatFilter === '1' ? '' : '1');
                  setCurrentPage(1);
                }}
              >
                <ImageIcon size={13} />
                <span>{t("تصاویر")}</span>
              </button>

              <button
                type="button"
                className={`quick-chip ${formatFilter === '8' ? 'active' : ''}`}
                onClick={() => {
                  setFormatFilter(formatFilter === '8' ? '' : '8');
                  setCurrentPage(1);
                }}
              >
                <Layers size={13} />
                <span>{t("چنداسلایدی")}</span>
              </button>

              <button
                type="button"
                className={`quick-chip ${sourceFilter === 'saved' ? 'active' : ''}`}
                onClick={() => {
                  setSourceFilter(sourceFilter === 'saved' ? '' : 'saved');
                  setCurrentPage(1);
                }}
              >
                <Bookmark size={13} />
                <span>{t("ذخیره‌ها")}</span>
              </button>

              <button
                type="button"
                className={`quick-chip ${sourceFilter === 'liked' ? 'active' : ''}`}
                onClick={() => {
                  setSourceFilter(sourceFilter === 'liked' ? '' : 'liked');
                  setCurrentPage(1);
                }}
              >
                <Heart size={13} />
                <span>{t("لایک‌ها")}</span>
              </button>

              <button
                type="button"
                className={`quick-chip ${statusFilter === 'DOWNLOAD_OK' ? 'active' : ''}`}
                onClick={() => {
                  setStatusFilter(statusFilter === 'DOWNLOAD_OK' ? '' : 'DOWNLOAD_OK');
                  setCurrentPage(1);
                }}
              >
                <FolderCheck size={13} />
                <span>{t("دانلودشده")}</span>
              </button>
            </div>

            {/* Custom Folders & Sort Controls */}
            <div className="library-sort-folder-group">
              <select 
                className="filter-select custom-folder-select" 
                value={customCategoryFilter} 
                onChange={(e) => {
                  setCustomCategoryFilter(e.target.value);
                  setCurrentPage(1);
                }}
                style={{ fontWeight: customCategoryFilter ? 600 : 400 }}
              >
                <option value="">📁 {t("همهٔ پوشه‌ها")}</option>
                {customCategories.map(c => (
                  <option key={c.id} value={c.id}>
                    📁 {c.name} ({c.folder_name})
                  </option>
                ))}
              </select>

              <div className="sort-dropdown-group">
                <select
                  className="filter-select sort-select"
                  value={sortBy}
                  onChange={(e) => {
                    setSortBy(e.target.value);
                    setCurrentPage(1);
                  }}
                  title={t("مرتب‌سازی بر اساس")}
                >
                  <option value="activity_date">{t("تاریخ فعالیت (هوشمند)")}</option>
                  <option value="saved_at">{t("تاریخ ذخیره در اینستاگرام")}</option>
                  <option value="liked_at">{t("تاریخ لایک در اینستاگرام")}</option>
                  <option value="taken_at">{t("تاریخ انتشار اصلی پست")}</option>
                  <option value="status_updated_at">{t("تاریخ دانلود / ثبت")}</option>
                </select>

                <button
                  type="button"
                  className="btn btn-sort-dir"
                  onClick={() => setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')}
                  title={sortOrder === 'desc' ? t("جدیدترین به قدیمی‌ترین (نزولی)") : t("قدیمی‌ترین به جدیدترین (صعودی)")}
                >
                  {sortOrder === 'desc' ? <ArrowDownWideNarrow size={16} /> : <ArrowUpNarrowWide size={16} />}
                </button>
              </div>

              {/* Advanced Filter Toggle Button */}
              <button
                type="button"
                className={`btn btn-toggle-advanced ${showAdvancedFilters || hasActiveFilters ? 'active' : ''}`}
                onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
                title={t("فیلترهای پیشرفته")}
              >
                <SlidersHorizontal size={15} />
                <span>{t("فیلترها")}</span>
                {hasActiveFilters && <span className="active-dot" />}
              </button>
            </div>
          </div>

          {/* Collapsible Advanced Filters Drawer */}
          {showAdvancedFilters && (
            <div className="advanced-filters-drawer animate-fade-in">
              <div className="advanced-filters-grid">
                {/* AI Category */}
                <div className="filter-field">
                  <label className="filter-label">{t("دسته‌بندی هوش مصنوعی:")}</label>
                  <select 
                    className="filter-select w-full" 
                    value={categoryFilter} 
                    onChange={(e) => { setCategoryFilter(e.target.value); setCurrentPage(1); }}
                  >
                    <option value="">{t("همهٔ دسته‌ها")}</option>
                    {categories.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>

                {/* Creator Filter */}
                <div className="filter-field">
                  <label className="filter-label">{t("منتشرکننده (سازنده):")}</label>
                  <select 
                    className="filter-select w-full" 
                    value={creatorFilter} 
                    onChange={e => { setCreatorFilter(e.target.value); setCurrentPage(1); }}
                  >
                    <option value="">{t("همهٔ منتشرکننده‌ها")}</option>
                    {creators.map(name => <option key={name} value={name}>@{name}</option>)}
                  </select>
                </div>

                {/* Status Filter */}
                <div className="filter-field">
                  <label className="filter-label">{t("وضعیت پست:")}</label>
                  <select 
                    className="filter-select w-full" 
                    value={statusFilter} 
                    onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }}
                  >
                    <option value="">{t("همهٔ وضعیت‌ها")}</option>
                    <option value="ORGANIZED">{t("دسته‌بندی‌شده")}</option>
                    <option value="DOWNLOAD_OK">{t("دانلودشده")}</option>
                    <option value="APPROVED">{t("تأییدشده با AI")}</option>
                    <option value="ANALYSIS_OK">{t("تحلیل‌شده با AI")}</option>
                    <option value="DISCOVERED">{t("فقط فهرست، بدون فایل")}</option>
                    <option value="REVIEW_REQUIRED">{t("نیازمند بازبینی AI")}</option>
                    <option value="ANALYSIS_FAILED">{t("خطای AI")}</option>
                    <option value="UNAVAILABLE">{t("ناموجود در اینستاگرام")}</option>
                    <option value="MISSING_LOCAL">{t("فایل محلی گم‌شده")}</option>
                  </select>
                </div>

                {/* Instagram Collections */}
                <div className="filter-field">
                  <label className="filter-label">{t("مجموعهٔ ذخیره‌شده:")}</label>
                  <select 
                    className="filter-select w-full" 
                    value={collectionFilter} 
                    onChange={e => { setCollectionFilter(e.target.value); setCurrentPage(1); }}
                  >
                    <option value="">{t("همهٔ مجموعه‌ها")}</option>
                    {collections.map(item => <option key={item.name} value={item.name}>{item.name} ({item.count})</option>)}
                  </select>
                </div>

                {/* Date From */}
                <div className="filter-field">
                  <label className="filter-label">{t("از تاریخ:")}</label>
                  <input 
                    type="date" 
                    className="meta-input w-full" 
                    value={fromDate} 
                    onChange={e => { setFromDate(e.target.value); setCurrentPage(1); }} 
                  />
                </div>

                {/* Date To */}
                <div className="filter-field">
                  <label className="filter-label">{t("تا تاریخ:")}</label>
                  <input 
                    type="date" 
                    className="meta-input w-full" 
                    value={toDate} 
                    onChange={e => { setToDate(e.target.value); setCurrentPage(1); }} 
                  />
                </div>
              </div>

              {hasActiveFilters && (
                <div className="advanced-filters-footer">
                  <button
                    type="button"
                    className="btn btn-sm btn-clear-filters"
                    onClick={clearAllFilters}
                  >
                    <RotateCcw size={14} />
                    <span>{t("پاک کردن تمام فیلترها")}</span>
                  </button>
                </div>
              )}
            </div>
          )}
        </header>

        {/* Floating Bulk Action Bar (when Select Mode is active) */}
        {isSelectMode && (
          <div className="bulk-actions-floating-bar animate-fade-in">
            <div className="bulk-selection-info">
              <button 
                type="button" 
                className="btn btn-sm btn-select-all" 
                onClick={handleSelectAllOnPage}
              >
                {selectedPks.size === posts.length && posts.length > 0 ? t("لغو انتخاب همه") : t("انتخاب تمام صفحه")}
              </button>
              <span className="selected-count-badge">
                {selectedPks.size} {t("مورد انتخاب شده")}
              </span>
            </div>

            <div className="bulk-action-controls">
              <select 
                className="filter-select bulk-category-select"
                value={bulkCategoryTarget}
                onChange={(e) => setBulkCategoryTarget(e.target.value)}
              >
                <option value="">{t("انتخاب پوشهٔ دسته‌بندی...")}</option>
                {customCategories.map(c => (
                  <option key={c.id} value={c.id}>
                    📁 {c.name}
                  </option>
                ))}
              </select>

              <button 
                type="button" 
                className="btn btn-primary btn-sm" 
                disabled={!bulkCategoryTarget || selectedPks.size === 0}
                onClick={handleBulkAssign}
              >
                + {t("افزودن به دسته")}
              </button>

              <button 
                type="button" 
                className="btn btn-sm btn-danger-soft" 
                disabled={!bulkCategoryTarget || selectedPks.size === 0}
                onClick={handleBulkRemove}
              >
                - {t("حذف از دسته")}
              </button>

              <button 
                type="button" 
                className="btn btn-sm btn-export" 
                disabled={selectedPks.size === 0}
                onClick={handleBulkExport}
                title={t("کپی کردن تمام فایل‌های انتخاب‌شده در یک پوشهٔ دلخواه در ویندوز")}
              >
                <FolderDown size={14} />
                <span>{t("خروجی به پوشه ویندوز")}</span>
              </button>
            </div>
          </div>
        )}

        {/* Status Alerts */}
        {bulkActionMessage && (
          <div className="toast-alert toast-success animate-fade-in">
            <Check size={16} />
            <span>{bulkActionMessage}</span>
          </div>
        )}

        {bulkActionError && (
          <div className="toast-alert toast-error animate-fade-in">
            <AlertCircle size={16} />
            <span>{bulkActionError}</span>
          </div>
        )}

        {importMessage && (
          <div className="toast-alert toast-info animate-fade-in">
            <Check size={16} />
            <span>{importMessage}</span>
          </div>
        )}

        {loadError && (
          <div className="toast-alert toast-error animate-fade-in">
            <AlertCircle size={16} />
            <span>{loadError}</span>
          </div>
        )}

        {/* Media Grid */}
        <div className="media-grid">
          {posts.map(post => (
            <MediaCard 
              key={post.pk} 
              post={post} 
              onClick={(p) => {
                if (isSelectMode) {
                  handleToggleSelectPost(p, !selectedPks.has(p.pk));
                } else {
                  setSelectedPost(p);
                }
              }}
              selectable={isSelectMode}
              selected={selectedPks.has(post.pk)}
              onToggleSelect={handleToggleSelectPost}
            />
          ))}

          {posts.length === 0 && (
            <div className="library-empty-state">
              <div className="empty-icon-circle">
                <Search size={36} color="var(--primary)" />
              </div>
              <h3 className="empty-title">{t("هیچ موردی مطابق فیلترهای کنونی یافت نشد.")}</h3>
              <p className="empty-desc">{t("می‌توانید فیلترها را پاک کنید یا عبارت دیگری را جستجو نمایید.")}</p>
              {hasActiveFilters && (
                <button type="button" className="btn btn-primary" onClick={clearAllFilters} style={{ marginTop: '12px' }}>
                  <RotateCcw size={15} />
                  <span>{t("پاک کردن فیلترها")}</span>
                </button>
              )}
            </div>
          )}
        </div>

        {/* Enterprise Bottom Pagination Bar */}
        {totalCount > 0 && (
          <footer className="library-pagination-bar">
            <div className="pagination-range-text">
              {language === 'fa' ? (
                <>
                  نمایش <strong>{startItem.toLocaleString('fa-IR')}</strong> تا <strong>{endItem.toLocaleString('fa-IR')}</strong> از <strong className="text-primary">{totalCount.toLocaleString('fa-IR')}</strong> پست
                </>
              ) : (
                <>
                  Showing <strong>{startItem.toLocaleString('en-US')}</strong>–<strong>{endItem.toLocaleString('en-US')}</strong> of <strong className="text-primary">{totalCount.toLocaleString('en-US')}</strong> posts
                </>
              )}
            </div>

            <div className="pagination-nav-group">
              <button 
                type="button" 
                className="btn btn-sm btn-page-nav" 
                disabled={currentPage <= 1}
                onClick={() => handlePageChange(currentPage - 1)}
              >
                <ChevronRight size={16} />
                <span>{t("قبلی")}</span>
              </button>

              <div className="pagination-page-indicator">
                {language === 'fa' ? (
                  <>
                    <span>صفحه</span>
                    <span className="current-page-num">{currentPage.toLocaleString('fa-IR')}</span>
                    <span>از</span>
                    <span className="total-pages-num">{totalPages.toLocaleString('fa-IR')}</span>
                  </>
                ) : (
                  <>
                    <span>Page</span>
                    <span className="current-page-num">{currentPage}</span>
                    <span>of</span>
                    <span className="total-pages-num">{totalPages}</span>
                  </>
                )}
              </div>

              <button 
                type="button" 
                className="btn btn-sm btn-page-nav" 
                disabled={currentPage >= totalPages}
                onClick={() => handlePageChange(currentPage + 1)}
              >
                <span>{t("بعدی")}</span>
                <ChevronLeft size={16} />
              </button>
            </div>

            <div className="pagination-pagesize-group">
              <label>{t("تعداد در صفحه:")}</label>
              <select 
                className="filter-select page-size-select"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setCurrentPage(1);
                }}
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={200}>200</option>
              </select>
            </div>
          </footer>
        )}
      </div>

      {/* Global Inspector Modal / Drawer */}
      <Inspector 
        post={selectedPost} 
        isOpen={!!selectedPost} 
        onClose={() => setSelectedPost(null)}
        onSave={handleSaveMetadata}
      />
    </div>
  );
};

export default Library;
