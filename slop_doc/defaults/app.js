/* slop-doc client-side app (SPA navigation, search, nav tree, scroll spy, sidebar sync) */
(function () {
  'use strict';

  /* ── Helpers ────────────────────────────────────────────── */

  function getIndex() { return window.__SEARCH_INDEX__ || []; }
  function getPrefix() { return window.__SEARCH_PREFIX__ || ''; }

  /** Resolve a relative href to an absolute URL using a temp anchor. */
  function toAbsolute(href) {
    var a = document.createElement('a');
    a.href = href;
    return a;
  }

  /** Check if an href points to an internal documentation page. */
  function isInternalLink(a) {
    if (!a || !a.href) return false;
    if (a.target === '_blank' || a.target === '_new') return false;
    var href = a.getAttribute('href');
    if (!href) return false;
    if (href.charAt(0) === '#') return false;
    // Reject absolute URLs to other origins
    if (/^https?:\/\//.test(href)) {
      try { if (new URL(href).origin !== location.origin) return false; }
      catch (e) { return false; }
    }
    // Must end with .html (with optional #anchor)
    var clean = href.split('#')[0].split('?')[0];
    if (clean && !/\.html$/.test(clean)) return false;
    return true;
  }

  /** Trigger highlight-fade animation on an element via JS. */
  var _lastFlashed = null;
  function flashHighlight(el) {
    if (!el) return;
    // Clear previous flash if still running
    if (_lastFlashed && _lastFlashed !== el) {
      _lastFlashed.classList.remove('highlight-flash');
    }
    _lastFlashed = el;
    el.classList.remove('highlight-flash');
    window.getComputedStyle(el).animation;
    el.classList.add('highlight-flash');
    el.addEventListener('animationend', function handler() {
      el.classList.remove('highlight-flash');
      el.removeEventListener('animationend', handler);
      if (_lastFlashed === el) _lastFlashed = null;
    });
  }

  /** Scroll to anchor and flash highlight. */
  function scrollToAnchor(anchor) {
    if (!anchor) return;
    var el = document.getElementById(anchor);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth' });
    flashHighlight(el);
  }

  /* ── SPA Navigation ────────────────────────────────────── */

  /** Fetch a page and swap content without full reload. */
  function navigateTo(url, pushState) {
    var parts = url.split('#');
    var pageUrl = parts[0];
    var anchor = parts[1] || null;

    // If same page — just scroll to anchor
    var resolved = toAbsolute(pageUrl);
    if (resolved.pathname === location.pathname && anchor) {
      scrollToAnchor(anchor);
      if (pushState) history.pushState(null, '', url);
      return;
    }

    fetch(resolved.href)
      .then(function (res) {
        if (!res.ok) throw new Error(res.status);
        return res.text();
      })
      .then(function (html) {
        swapContent(html, url, anchor, pushState);
      })
      .catch(function () {
        location.href = url;
      });
  }

  /** Parse fetched HTML and swap the dynamic parts of the page. */
  function swapContent(html, url, anchor, pushState) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(html, 'text/html');

    var newContent = doc.querySelector('.content');
    var newSidebarRight = doc.querySelector('.sidebar-right');
    var newBreadcrumb = doc.querySelector('.breadcrumb');
    var newTitle = doc.title;
    var newNav = doc.querySelector('.sidebar-left');

    if (!newContent) {
      location.href = url;
      return;
    }

    document.title = newTitle;

    // Swap center content with fade animation
    var content = document.querySelector('.content');
    content.style.animation = 'none';
    void content.offsetHeight;
    content.innerHTML = newContent.innerHTML;
    content.style.animation = '';

    // Swap right sidebar
    var sidebarRight = document.querySelector('.sidebar-right');
    if (sidebarRight && newSidebarRight) {
      sidebarRight.innerHTML = newSidebarRight.innerHTML;
    } else if (sidebarRight && !newSidebarRight) {
      sidebarRight.innerHTML = '';
    }

    // Update breadcrumb
    var breadcrumb = document.querySelector('.breadcrumb');
    if (breadcrumb && newBreadcrumb) {
      breadcrumb.innerHTML = newBreadcrumb.innerHTML;
    }

    // Update nav tree (active states and hrefs)
    if (newNav) {
      var sidebarLeft = document.querySelector('.sidebar-left');
      sidebarLeft.innerHTML = newNav.innerHTML;
      restoreNavState();
    }

    // Extract and update search index + prefix
    var scripts = doc.querySelectorAll('script');
    for (var i = 0; i < scripts.length; i++) {
      var text = scripts[i].textContent;
      if (text.indexOf('__SEARCH_INDEX__') !== -1) {
        try {
          var idxMatch = text.match(/window\.__SEARCH_INDEX__\s*=\s*([\s\S]*?);[\s\n]*\/\//);
          if (!idxMatch) idxMatch = text.match(/window\.__SEARCH_INDEX__\s*=\s*([\s\S]*?);/);
          var prefixMatch = text.match(/window\.__SEARCH_PREFIX__\s*=\s*'([^']*)'/);
          if (idxMatch) window.__SEARCH_INDEX__ = JSON.parse(idxMatch[1]);
          if (prefixMatch) window.__SEARCH_PREFIX__ = prefixMatch[1];
        } catch (e) { /* ignore */ }
      }
    }

    if (pushState) {
      history.pushState(null, '', url);
    }

    // Scroll to anchor or top
    if (anchor) {
      requestAnimationFrame(function () {
        scrollToAnchor(anchor);
      });
    } else {
      window.scrollTo(0, 0);
    }

    // Re-init scroll spy and PDF viewer
    initScrollSpy();
    initInlineScrollSpy();
    initPdfViewer();
  }

  /** Restore nav expand/collapse state from localStorage after nav replacement. */
  function restoreNavState() {
    var STORAGE_KEY = 'nav-expanded';
    var saved;
    try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
    catch (e) { saved = {}; }

    document.querySelectorAll('[data-nav-id]').forEach(function (li) {
      var id = li.getAttribute('data-nav-id');
      if (id in saved) setExpanded(li, saved[id]);
    });

    // Re-bind toggle handlers
    document.querySelectorAll('.nav-toggle').forEach(function (toggle) {
      toggle.addEventListener('click', function (e) {
        e.stopPropagation();
        var li = toggle.closest('[data-nav-id]');
        if (!li) return;
        var nowExpanded = !li.classList.contains('expanded');
        setExpanded(li, nowExpanded);
        var state;
        try { state = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
        catch (e) { state = {}; }
        state[li.getAttribute('data-nav-id')] = nowExpanded;
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
      });
    });

    // Re-bind nav link expand on click
    document.querySelectorAll('.has-children > a').forEach(function (link) {
      link.addEventListener('click', function () {
        var li = link.closest('[data-nav-id]');
        if (!li || li.classList.contains('expanded')) return;
        setExpanded(li, true);
        var state;
        try { state = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
        catch (e) { state = {}; }
        state[li.getAttribute('data-nav-id')] = true;
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
      });
    });
  }

  function setExpanded(li, expanded) {
    li.classList.toggle('expanded', expanded);
    li.classList.toggle('collapsed', !expanded);
    for (var i = 0; i < li.children.length; i++) {
      var ch = li.children[i];
      if (ch.classList && ch.classList.contains('nav-children')) {
        ch.classList.toggle('expanded', expanded);
        ch.classList.toggle('collapsed', !expanded);
        break;
      }
    }
  }

  /* ── Search ────────────────────────────────────────────── */

  var input, dropdown;

  function initSearch() {
    input = document.getElementById('search-input');
    dropdown = null;
    if (!input) return;

    input.addEventListener('input', function () { search(this.value.trim()); });
    input.addEventListener('focus', function () { if (this.value.trim()) search(this.value.trim()); });

    document.addEventListener('click', function (e) {
      if (input && !input.parentNode.contains(e.target)) hideResults();
    });
  }

  function createDropdown() {
    dropdown = document.createElement('ul');
    dropdown.id = 'search-results';
    dropdown.style.cssText =
      'position:absolute;top:100%;left:0;right:0;background:#252525;border:1px solid #444;' +
      'border-radius:4px;list-style:none;padding:4px 0;margin:0;width:100%;' +
      'max-height:320px;overflow-y:auto;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.4);' +
      'transition:opacity .15s ease;opacity:0';
    input.parentNode.style.position = 'relative';
    input.parentNode.appendChild(dropdown);
  }

  function showResults(results) {
    if (!dropdown) createDropdown();
    dropdown.innerHTML = '';
    if (!results.length) {
      var li = document.createElement('li');
      li.textContent = 'No results';
      li.style.cssText = 'padding:8px 14px;color:#888;font-size:14px';
      dropdown.appendChild(li);
    } else {
      results.slice(0, 12).forEach(function (r) {
        var li = document.createElement('li');
        var a = document.createElement('a');
        a.href = getPrefix() + r.url;
        a.textContent = r.title;
        a.style.cssText =
          'display:block;padding:6px 14px;color:#e3e3e3;text-decoration:none;font-size:14px';
        a.onmouseover = function () { a.style.background = '#3a3a3a'; };
        a.onmouseout = function () { a.style.background = ''; };
        li.appendChild(a);
        dropdown.appendChild(li);
      });
    }
    dropdown.style.display = 'block';
    void dropdown.offsetHeight;
    dropdown.style.opacity = '1';
  }

  function hideResults() {
    if (dropdown) { dropdown.style.opacity = '0'; dropdown.style.display = 'none'; }
  }

  function search(query) {
    var index = getIndex();
    if (!index || !query) { hideResults(); return; }
    var q = query.toLowerCase();
    var results = index.filter(function (e) {
      return e.title.toLowerCase().indexOf(q) !== -1;
    });
    showResults(results);
  }

  /* ── Scroll spy (right sidebar) ────────────────────────── */

  function initScrollSpy() {
    var links = document.querySelectorAll('.contents-sidebar a');
    if (!links.length) return;

    if (window._slopScrollSpy) {
      window.removeEventListener('scroll', window._slopScrollSpy);
    }

    function onScroll() {
      var scrollY = window.scrollY + 80;
      var current = null;
      links.forEach(function (a) {
        var id = a.getAttribute('href').slice(1);
        var el = document.getElementById(id);
        if (el && el.offsetTop <= scrollY) current = a;
      });
      links.forEach(function (a) { a.classList.remove('current'); });
      if (current) current.classList.add('current');
    }

    window._slopScrollSpy = onScroll;
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ── Inline scroll spy (method details + headings) ─────── */

  function initInlineScrollSpy() {
    var tocLinks = document.querySelectorAll('.contents-sidebar a');
    var headings = [];

    document.querySelectorAll('h2[id], h3[id], .method-detail[id]').forEach(function (el) {
      headings.push({ id: el.id, el: el });
    });

    if (window._slopInlineScrollSpy) {
      window.removeEventListener('scroll', window._slopInlineScrollSpy);
    }

    function highlightCurrent() {
      var scrollY = window.scrollY + 60;
      var current = null;
      for (var i = headings.length - 1; i >= 0; i--) {
        if (headings[i].el.offsetTop <= scrollY) {
          current = headings[i].id;
          break;
        }
      }
      tocLinks.forEach(function (link) {
        link.classList.remove('current');
        if (current && link.getAttribute('href') === '#' + current) {
          link.classList.add('current');
          link.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      });
    }

    window._slopInlineScrollSpy = highlightCurrent;
    window.addEventListener('scroll', highlightCurrent, { passive: true });
    highlightCurrent();
  }

  /* ── Sidebar width sync ────────────────────────────────── */

  function initSidebarSync() {
    var sidebar = document.querySelector('.sidebar-left');
    if (!sidebar || typeof ResizeObserver === 'undefined') return;
    new ResizeObserver(function () {
      document.documentElement.style.setProperty('--sidebar-w', sidebar.offsetWidth + 'px');
    }).observe(sidebar);
  }

  /* ── Global click interceptor for SPA nav ──────────────── */

  function initSpaClickHandler() {
    document.addEventListener('click', function (e) {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;

      var link = e.target.closest('a[href]');
      if (!link) return;
      var href = link.getAttribute('href');
      if (!href) return;

      // Pure hash links (#anchor) on the same page — handle with scroll + flash
      if (href.charAt(0) === '#') {
        e.preventDefault();
        scrollToAnchor(href.slice(1));
        history.pushState(null, '', href);
        return;
      }

      if (!isInternalLink(link)) return;

      e.preventDefault();
      hideResults();
      navigateTo(href, true);
    });

    // Handle browser back/forward
    window.addEventListener('popstate', function () {
      var hash = location.hash ? location.hash.slice(1) : null;
      // If just a hash change on the same page, scroll to it
      if (hash && document.getElementById(hash)) {
        scrollToAnchor(hash);
        return;
      }
      navigateTo(location.pathname + location.search + location.hash, false);
    });
  }

  /* ── PDF Viewer (iframe, no toolbar) ────────────────────── */

  function initPdfViewer() {
    var viewers = document.querySelectorAll('.pdf-viewer[data-pdf-url]');
    if (!viewers.length) return;

    viewers.forEach(function (viewer) {
      if (viewer.querySelector('iframe')) return; // already initialized
      var url = viewer.dataset.pdfUrl + '#toolbar=0&navpanes=0&scrollbar=1&view=FitH';
      var iframe = document.createElement('iframe');
      iframe.src = url;
      iframe.style.cssText = 'width:140%;border:none;display:block;margin-left:-7.5%;';
      viewer.innerHTML = '';
      viewer.appendChild(iframe);

      iframe.style.height = '95vh';
    });
  }

  /* ── Init ──────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', function () {
    initSearch();
    initScrollSpy();
    initInlineScrollSpy();
    restoreNavState();
    initSidebarSync();
    initSpaClickHandler();
    initPdfViewer();
  });

}());
