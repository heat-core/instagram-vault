import { useI18n } from '../i18n';
import { useState, useEffect } from 'react';
import { Bookmark, Bot, Folder, Search, Sparkles, Plus, Edit2, Trash2, FolderDown, Check, AlertCircle, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const API_BASE = 'http://127.0.0.1:8000';

interface CategoryItem {
  name: string;
  count: number;
}

interface CustomCategoryItem {
  id: number;
  name: string;
  folder_name: string;
  description?: string;
  color: string;
  count: number;
  created_at?: number;
}

const COLOR_PRESETS = [
  '#a855f7', // Purple
  '#3b82f6', // Blue
  '#10b981', // Emerald
  '#f59e0b', // Amber
  '#ec4899', // Pink
  '#06b6d4', // Cyan
  '#ef4444', // Red
  '#8b5cf6', // Violet
];

const Categories = () => {
  const { t, language } = useI18n();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'custom' | 'collections' | 'ai'>('custom');
  const [customCategories, setCustomCategories] = useState<CustomCategoryItem[]>([]);
  const [collections, setCollections] = useState<CategoryItem[]>([]);
  const [aiCategories, setAiCategories] = useState<CategoryItem[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<CustomCategoryItem | null>(null);
  const [modalForm, setModalForm] = useState({
    name: '',
    folder_name: '',
    description: '',
    color: COLOR_PRESETS[0]
  });
  const [modalError, setModalError] = useState('');

  // Toasts
  const [toastMessage, setToastMessage] = useState('');
  const [toastError, setToastError] = useState('');
  const [exportingId, setExportingId] = useState<number | null>(null);

  const fetchSummary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/categories/summary`);
      if (res.ok) {
        const data = await res.json();
        setCollections(data.collections || []);
        setAiCategories(data.ai_categories || []);
        setCustomCategories(data.custom_categories || []);
      }
    } catch (e) {
      console.error("Failed to fetch category summary", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSummary();
  }, []);

  const openCreateModal = () => {
    setEditingCategory(null);
    setModalForm({
      name: '',
      folder_name: '',
      description: '',
      color: COLOR_PRESETS[Math.floor(Math.random() * COLOR_PRESETS.length)]
    });
    setModalError('');
    setIsModalOpen(true);
  };

  const openEditModal = (cat: CustomCategoryItem, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingCategory(cat);
    setModalForm({
      name: cat.name,
      folder_name: cat.folder_name,
      description: cat.description || '',
      color: cat.color || COLOR_PRESETS[0]
    });
    setModalError('');
    setIsModalOpen(true);
  };

  const handleNameChange = (name: string) => {
    setModalForm(prev => {
      // Auto-suggest folder name if creating new and folder_name hasn't been manually diverged
      const autoFolder = !editingCategory && (!prev.folder_name || prev.folder_name === slugify(prev.name))
        ? slugify(name)
        : prev.folder_name;
      return { ...prev, name, folder_name: autoFolder };
    });
  };

  const slugify = (text: string) => {
    return text
      .trim()
      .toLowerCase()
      .replace(/[\s\-_]+/g, '_')
      .replace(/[^\w\u0600-\u06FF]/g, '')
      .slice(0, 40);
  };

  const handleSaveModal = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError('');

    if (!modalForm.name.trim()) {
      setModalError(t('نام دسته‌بندی الزامی است.'));
      return;
    }

    const folder = modalForm.folder_name.trim() || slugify(modalForm.name);
    try {
      if (editingCategory) {
        // Update
        const res = await fetch(`${API_BASE}/custom-categories/${editingCategory.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: modalForm.name.trim(),
            folder_name: folder,
            description: modalForm.description.trim() || null,
            color: modalForm.color
          })
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Failed to update category');
        setToastMessage(t('دسته‌بندی با موفقیت ویرایش شد.'));
      } else {
        // Create
        const res = await fetch(`${API_BASE}/custom-categories`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: modalForm.name.trim(),
            folder_name: folder,
            description: modalForm.description.trim() || null,
            color: modalForm.color
          })
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Failed to create category');
        setToastMessage(t('دسته‌بندی و پوشه جدید با موفقیت ایجاد شد.'));
      }
      setIsModalOpen(false);
      fetchSummary();
      setTimeout(() => setToastMessage(''), 3500);
    } catch (err: any) {
      setModalError(String(err.message || err));
    }
  };

  const handleDeleteCategory = async (cat: CustomCategoryItem, e: React.MouseEvent) => {
    e.stopPropagation();
    const confirmMsg = language === 'fa' 
      ? `آیا از حذف دسته‌بندی «${cat.name}» مطمئن هستید؟ (پست‌های شما حذف نمی‌شوند)` 
      : `Are you sure you want to delete category "${cat.name}"? (Your posts will not be deleted)`;
    if (!confirm(confirmMsg)) return;

    try {
      const res = await fetch(`${API_BASE}/custom-categories/${cat.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed to delete');
      setToastMessage(t('دسته‌بندی با موفقیت حذف شد.'));
      fetchSummary();
      setTimeout(() => setToastMessage(''), 3500);
    } catch (err: any) {
      setToastError(String(err.message || err));
      setTimeout(() => setToastError(''), 3500);
    }
  };

  const handleExportToFolder = async (cat: CustomCategoryItem, e: React.MouseEvent) => {
    e.stopPropagation();
    setExportingId(cat.id);
    try {
      const res = await fetch(`${API_BASE}/custom-categories/${cat.id}/export-folder`, { method: 'POST' });
      if (!res.ok) throw new Error((await res.json()).detail || 'Export failed');
      const data = await res.json();
      const count = data.exported_count ?? data.exported ?? 0;
      const folder = data.folder_path ?? data.folder ?? '';
      setToastMessage(language === 'fa' ? `${count} فایل در پوشه ${folder} سازماندهی شد.` : `${count} files organized in folder ${folder}.`);
      setTimeout(() => setToastMessage(''), 5000);
    } catch (err: any) {
      setToastError(String(err.message || err));
      setTimeout(() => setToastError(''), 4000);
    } finally {
      setExportingId(null);
    }
  };

  const handleCustomCategoryClick = (id: number) => {
    navigate(`/library?custom_category_id=${id}`);
  };

  const handleCollectionClick = (name: string) => {
    navigate(`/library?collection=${encodeURIComponent(name)}`);
  };

  const handleAiCategoryClick = (name: string) => {
    navigate(`/library?category=${encodeURIComponent(name)}`);
  };

  const filteredCustomCategories = customCategories.filter(c =>
    c.name.toLowerCase().includes(search.trim().toLowerCase()) ||
    c.folder_name.toLowerCase().includes(search.trim().toLowerCase())
  );

  const filteredCollections = collections.filter(c =>
    c.name.toLowerCase().includes(search.trim().toLowerCase())
  );

  const filteredAiCategories = aiCategories.filter(c =>
    c.name.toLowerCase().includes(search.trim().toLowerCase())
  );

  return (
    <div className="view-container animate-fade-in" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 className="view-title" style={{ display: 'flex', alignItems: 'center', gap: '10px', margin: 0 }}>
            <Folder size={26} color="var(--primary)" /> {t("دسته‌بندی‌ها و پوشه‌های اختصاصی")}
          </h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: '6px' }}>
            {t("ساخت پوشه‌ها و دسته‌بندی‌های دلخواه، خروجی به دیسک، یا مرور بر اساس مجموعه‌های اینستاگرام و AI.")}
          </p>
        </div>

        {/* Action & Search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', minWidth: '220px' }}>
            <input
              type="text"
              className="meta-input"
              placeholder={t("جستجوی پوشه یا دسته...")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ padding: '8px 12px 8px 36px', fontSize: '13px', width: '100%' }}
            />
            <Search size={15} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-secondary)' }} />
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={openCreateModal}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px' }}
          >
            <Plus size={16} /> {t("ساخت دسته‌بندی جدید")}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '12px', borderBottom: '1px solid var(--border)', paddingBottom: '12px', flexWrap: 'wrap' }}>
        <button
          className={`btn ${activeTab === 'custom' ? 'btn-primary' : ''}`}
          onClick={() => setActiveTab('custom')}
          style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          <Folder size={16} />
          {t("دسته‌بندی‌ها و پوشه‌های من")}
          {customCategories.length > 0 && (
            <span className="badge" style={{ background: activeTab === 'custom' ? 'rgba(255,255,255,0.2)' : 'var(--bg-card)' }}>
              {customCategories.length}
            </span>
          )}
        </button>

        <button
          className={`btn ${activeTab === 'collections' ? 'btn-primary' : ''}`}
          onClick={() => setActiveTab('collections')}
          style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          <Bookmark size={16} />
          {t("مجموعه‌های اینستاگرام شما")}
          {collections.length > 0 && (
            <span className="badge" style={{ background: activeTab === 'collections' ? 'rgba(255,255,255,0.2)' : 'var(--bg-card)' }}>
              {collections.length}
            </span>
          )}
        </button>

        <button
          className={`btn ${activeTab === 'ai' ? 'btn-primary' : ''}`}
          onClick={() => setActiveTab('ai')}
          style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          <Bot size={16} />
          {t("دسته‌بندی‌های هوش مصنوعی")}
          {aiCategories.length > 0 && (
            <span className="badge" style={{ background: activeTab === 'ai' ? 'rgba(255,255,255,0.2)' : 'var(--bg-card)' }}>
              {aiCategories.length}
            </span>
          )}
        </button>
      </div>

      {/* Toasts */}
      {toastMessage && (
        <div style={{ padding: '12px 16px', borderRadius: '8px', background: 'rgba(34, 197, 94, 0.15)', color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Check size={18} /> {toastMessage}
        </div>
      )}

      {toastError && (
        <div style={{ padding: '12px 16px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.15)', color: 'var(--error)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <AlertCircle size={18} /> {toastError}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div style={{ padding: '50px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          {t("در حال بارگذاری دسته‌بندی‌ها...")}
        </div>
      ) : activeTab === 'custom' ? (
        /* Custom User Categories Grid */
        <div>
          <div style={{ marginBottom: '14px', fontSize: '13px', color: 'var(--text-secondary)' }}>
            {filteredCustomCategories.length} {t("دسته‌بندی اختصاصی یافت شد")}
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: '16px'
          }}>
            {filteredCustomCategories.map(cat => (
              <div
                key={cat.id}
                className="card"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  padding: '18px',
                  borderRadius: '12px',
                  cursor: 'pointer',
                  border: '1px solid var(--border)',
                  borderTop: `4px solid ${cat.color || 'var(--primary)'}`,
                  transition: 'all 0.2s ease',
                  background: 'var(--bg-card)',
                  gap: '12px'
                }}
                onClick={() => handleCustomCategoryClick(cat.id)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-3px)';
                  e.currentTarget.style.borderColor = cat.color || 'var(--primary)';
                  e.currentTarget.style.boxShadow = '0 6px 16px rgba(0,0,0,0.2)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.borderColor = 'var(--border)';
                  e.currentTarget.style.borderTopColor = cat.color || 'var(--primary)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div style={{
                      width: '40px',
                      height: '40px',
                      borderRadius: '10px',
                      background: `${cat.color || 'var(--primary)'}22`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0
                    }}>
                      <Folder size={20} color={cat.color || 'var(--primary)'} />
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '15px' }}>{cat.name}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px', fontFamily: 'monospace' }}>
                        📁 {cat.folder_name}
                      </div>
                    </div>
                  </div>

                  <span className="badge" style={{ background: 'var(--bg-main)', fontSize: '12px' }}>
                    {cat.count} {t("پست")}
                  </span>
                </div>

                {cat.description && (
                  <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '4px 0', lineHeight: 1.5, maxHeight: '36px', overflow: 'hidden' }}>
                    {cat.description}
                  </p>
                )}

                {/* Card Actions */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '10px', borderTop: '1px solid var(--border)', marginTop: 'auto' }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{ fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    onClick={(e) => handleExportToFolder(cat, e)}
                    disabled={exportingId === cat.id || cat.count === 0}
                    title={t("ایجاد یا همگام‌سازی پوشه فایل‌ها روی دیسک")}
                  >
                    <FolderDown size={13} color="var(--primary)" />
                    {exportingId === cat.id ? t("در حال انتقال...") : t("خروجی به پوشه")}
                  </button>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ padding: '4px 8px' }}
                      onClick={(e) => openEditModal(cat, e)}
                      title={t("ویرایش دسته‌بندی")}
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ padding: '4px 8px', color: 'var(--error)' }}
                      onClick={(e) => handleDeleteCategory(cat, e)}
                      title={t("حذف دسته‌بندی")}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </div>
            ))}

            {filteredCustomCategories.length === 0 && (
              <div className="card" style={{ gridColumn: '1 / -1', padding: '50px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                <Folder size={40} style={{ opacity: 0.4, margin: '0 auto 12px' }} />
                <p style={{ fontSize: '15px', fontWeight: 600 }}>{t("هیچ دسته‌بندی یا پوشهٔ اختصاصی ساخته نشده است.")}</p>
                <p style={{ fontSize: '13px', marginTop: '6px' }}>
                  {t("با کلیک بر روی «ساخت دسته‌بندی جدید» می‌توانید دسته‌های دلخواه خود را بسازید و پست‌ها را در آن‌ها قرار دهید.")}
                </p>
                <button type="button" className="btn btn-primary" onClick={openCreateModal} style={{ marginTop: '16px' }}>
                  <Plus size={16} /> {t("ساخت اولین دسته‌بندی")}
                </button>
              </div>
            )}
          </div>
        </div>
      ) : activeTab === 'collections' ? (
        /* Instagram Collections Grid */
        <div>
          <div style={{ marginBottom: '14px', fontSize: '13px', color: 'var(--text-secondary)' }}>
            {filteredCollections.length} {t("مجموعه یافت شد")}
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: '16px'
          }}>
            {filteredCollections.map(item => (
              <div
                key={item.name}
                className="card"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '14px',
                  cursor: 'pointer',
                  padding: '20px',
                  transition: 'all 0.2s ease',
                  border: '1px solid var(--border)'
                }}
                onClick={() => handleCollectionClick(item.name)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-3px)';
                  e.currentTarget.style.borderColor = 'var(--primary)';
                  e.currentTarget.style.boxShadow = '0 6px 16px rgba(0,0,0,0.2)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.borderColor = 'var(--border)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div style={{
                  width: '46px',
                  height: '46px',
                  borderRadius: '10px',
                  background: 'rgba(168, 85, 247, 0.12)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0
                }}>
                  <Bookmark size={22} color="var(--primary)" />
                </div>
                <div style={{ overflow: 'hidden', flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '15px', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                    {item.name}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '3px' }}>
                    {item.count} {t("پست")}
                  </div>
                </div>
              </div>
            ))}

            {filteredCollections.length === 0 && (
              <div className="card" style={{ gridColumn: '1 / -1', padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                {collections.length === 0
                  ? t("هنوز فایل خروجی اینستاگرام (Saved Collections) وارد نشده است.")
                  : t("مجموعه‌ای مطابق جستجو یافت نشد.")}
              </div>
            )}
          </div>
        </div>
      ) : (
        /* AI Categories Grid */
        <div>
          <div style={{ marginBottom: '14px', fontSize: '13px', color: 'var(--text-secondary)' }}>
            {filteredAiCategories.length} {t("دسته‌بندی هوش مصنوعی")}
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: '16px'
          }}>
            {filteredAiCategories.map(item => (
              <div
                key={item.name}
                className="card"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '14px',
                  cursor: 'pointer',
                  padding: '20px',
                  transition: 'all 0.2s ease',
                  border: '1px solid var(--border)'
                }}
                onClick={() => handleAiCategoryClick(item.name)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-3px)';
                  e.currentTarget.style.borderColor = 'var(--primary)';
                  e.currentTarget.style.boxShadow = '0 6px 16px rgba(0,0,0,0.2)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.borderColor = 'var(--border)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div style={{
                  width: '46px',
                  height: '46px',
                  borderRadius: '10px',
                  background: 'rgba(59, 130, 246, 0.12)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0
                }}>
                  <Sparkles size={22} color="#3b82f6" />
                </div>
                <div style={{ overflow: 'hidden', flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '15px', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                    {item.name.split('/').pop() || item.name}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '3px' }}>
                    {item.count} {t("پست")}
                  </div>
                </div>
              </div>
            ))}

            {filteredAiCategories.length === 0 && (
              <div className="card" style={{ gridColumn: '1 / -1', padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                {aiCategories.length === 0
                  ? t("هنوز پستی توسط هوش مصنوعی دسته‌بندی نشده است. در تب «بازبینی هوش مصنوعی» یا داشبورد تحلیل را اجرا کنید.")
                  : t("دسته‌ای مطابق جستجو یافت نشد.")}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Create / Edit Custom Category Modal */}
      {isModalOpen && (
        <div 
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            background: 'rgba(0,0,0,0.6)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px'
          }}
          onClick={() => setIsModalOpen(false)}
        >
          <div 
            className="card"
            style={{
              width: '100%',
              maxWidth: '480px',
              padding: '24px',
              borderRadius: '12px',
              background: 'var(--bg-main)',
              border: '1px solid var(--border)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ fontSize: '17px', fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Folder size={18} color="var(--primary)" />
                {editingCategory ? t("ویرایش دسته‌بندی") : t("ساخت دسته‌بندی و پوشه جدید")}
              </h2>
              <button type="button" className="close-btn" onClick={() => setIsModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveModal} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label className="meta-label">{t("نام دسته‌بندی (فارسی یا انگلیسی)")}</label>
                <input 
                  type="text" 
                  className="meta-input" 
                  placeholder={t("مثال: معماری و دکوراسیون")} 
                  value={modalForm.name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  autoFocus
                />
              </div>

              <div>
                <label className="meta-label">{t("نام پوشه فیزیکی روی دیسک (archive/custom_folders/...)")}</label>
                <input 
                  type="text" 
                  className="meta-input" 
                  dir="ltr"
                  placeholder="architecture" 
                  value={modalForm.folder_name}
                  onChange={(e) => setModalForm({ ...modalForm, folder_name: e.target.value })}
                />
              </div>

              <div>
                <label className="meta-label">{t("توضیحات (اختیاری)")}</label>
                <textarea 
                  className="meta-textarea" 
                  style={{ minHeight: '60px' }}
                  placeholder={t("توضیحی کوتاه درباره محتوای این دسته...")}
                  value={modalForm.description}
                  onChange={(e) => setModalForm({ ...modalForm, description: e.target.value })}
                />
              </div>

              <div>
                <label className="meta-label">{t("رنگ برچسب")}</label>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '6px' }}>
                  {COLOR_PRESETS.map((color) => (
                    <button
                      key={color}
                      type="button"
                      onClick={() => setModalForm({ ...modalForm, color })}
                      style={{
                        width: '28px',
                        height: '28px',
                        borderRadius: '50%',
                        backgroundColor: color,
                        border: modalForm.color === color ? '3px solid white' : '2px solid transparent',
                        outline: modalForm.color === color ? `2px solid ${color}` : 'none',
                        cursor: 'pointer'
                      }}
                    />
                  ))}
                </div>
              </div>

              {modalError && (
                <div style={{ color: 'var(--error)', fontSize: '13px', background: 'rgba(239, 68, 68, 0.1)', padding: '8px 12px', borderRadius: '6px' }}>
                  {modalError}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" className="btn" onClick={() => setIsModalOpen(false)}>
                  {t("انصراف")}
                </button>
                <button type="submit" className="btn btn-primary">
                  {editingCategory ? t("ذخیره تغییرات") : t("ایجاد دسته‌بندی")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Categories;
