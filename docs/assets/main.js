// MemPalace docs — UI enhancements

(function () {
  // --- Sidebar drawer toggle (mobile) ---
  const sidebarToggle = document.querySelector('.sidebar-toggle');
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');

  const closeSidebar = () => {
    if (!sidebar) return;
    sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
    if (sidebarToggle) sidebarToggle.setAttribute('aria-expanded', 'false');
  };

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
      const isOpen = sidebar.classList.toggle('open');
      if (backdrop) backdrop.classList.toggle('open', isOpen);
      sidebarToggle.setAttribute('aria-expanded', String(isOpen));
    });
  }
  if (backdrop) backdrop.addEventListener('click', closeSidebar);

  // Close sidebar on escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeSidebar();
  });

  // --- Copy-to-clipboard on code blocks ---
  document.querySelectorAll('pre').forEach((pre) => {
    // Skip pres explicitly opted out (e.g. ASCII art previews on landing).
    if (pre.hasAttribute('data-no-copy') || pre.closest('[data-no-copy]')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-btn';
    btn.textContent = 'Copy';
    btn.setAttribute('aria-label', 'Copy code');

    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code') || pre;
      const text = code.innerText;
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = 'Copied';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }, 1600);
      } catch {
        btn.textContent = 'Error';
      }
    });

    pre.appendChild(btn);
  });

  // --- Generic [data-copy] buttons (e.g. landing CTA spotlight) ---
  document.querySelectorAll('button[data-copy]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const text = btn.getAttribute('data-copy') || '';
      const original = btn.textContent;
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = 'Copied';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = original;
          btn.classList.remove('copied');
        }, 1600);
      } catch {
        btn.textContent = 'Error';
      }
    });
  });

  // --- Right TOC scrollspy ---
  const tocLinks = document.querySelectorAll('.docs-toc a[href^="#"]');
  if (tocLinks.length > 0) {
    const sections = Array.from(tocLinks)
      .map((link) => {
        const id = decodeURIComponent(link.getAttribute('href').slice(1));
        return { id, el: document.getElementById(id), link };
      })
      .filter((s) => s.el);

    const setActive = () => {
      const scrollY = window.scrollY + 120;
      let current = sections[0];
      for (const s of sections) {
        if (s.el.offsetTop <= scrollY) current = s;
      }
      tocLinks.forEach((l) => l.classList.remove('active'));
      if (current) current.link.classList.add('active');
    };

    window.addEventListener('scroll', setActive, { passive: true });
    setActive();
  }

  // --- Mark current top nav link active ---
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  document.querySelectorAll('.topbar-nav a[href]').forEach((a) => {
    const href = a.getAttribute('href');
    if (!href || href.startsWith('http')) return;
    const normalized = href.replace(/\/$/, '') || '/';
    if (path.endsWith(normalized) && normalized !== '/') {
      a.classList.add('active');
    }
  });
})();
