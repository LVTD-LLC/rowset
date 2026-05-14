import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["list", "content", "sidebar"];

  connect() {
    this.generateTableOfContents();
    this.highlightCurrentSection();
    this.boundHandleScroll = this.handleScroll.bind(this);
    window.addEventListener("scroll", this.boundHandleScroll, { passive: true });
  }

  disconnect() {
    window.removeEventListener("scroll", this.boundHandleScroll);
  }

  generateTableOfContents() {
    if (!this.hasContentTarget || !this.hasListTarget) {
      return;
    }

    const headings = this.contentTarget.querySelectorAll("h2");

    if (headings.length === 0) {
      if (this.hasSidebarTarget) {
        this.sidebarTarget.style.display = "none";
      }
      return;
    }

    const tocItems = [];

    headings.forEach((heading) => {
      const headingText = heading.textContent.trim();

      let headingId = heading.id;
      if (!headingId) {
        headingId = this.generateSlug(headingText);
        heading.id = headingId;
      }

      const listItem = document.createElement("li");

      const link = document.createElement("a");
      link.href = `#${headingId}`;
      link.textContent = headingText;
      link.dataset.tocTarget = "link";
      link.dataset.section = headingId;
      link.className = `block rounded-lg px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-slate-100 hover:text-gray-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100`;

      link.addEventListener("click", (event) => {
        event.preventDefault();
        this.scrollToSection(headingId);
      });

      listItem.appendChild(link);
      tocItems.push(listItem);
    });

    this.listTarget.innerHTML = "";
    tocItems.forEach(item => this.listTarget.appendChild(item));
  }

  generateSlug(text) {
    return text
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .trim();
  }

  scrollToSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
      const yOffset = -80;
      const elementPosition = section.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset + yOffset;

      window.scrollTo({
        top: offsetPosition,
        behavior: "smooth"
      });

      this.updateActiveLink(sectionId);
    }
  }

  handleScroll() {
    this.highlightCurrentSection();
  }

  highlightCurrentSection() {
    if (!this.hasContentTarget) {
      return;
    }

    const headings = this.contentTarget.querySelectorAll("h2");
    const scrollPosition = window.scrollY + 100;

    let currentSectionId = "";

    headings.forEach((heading) => {
      const headingPosition = heading.offsetTop;
      if (scrollPosition >= headingPosition) {
        currentSectionId = heading.id;
      }
    });

    if (currentSectionId) {
      this.updateActiveLink(currentSectionId);
    }
  }

  updateActiveLink(activeSectionId) {
    const links = this.element.querySelectorAll("[data-toc-target='link']");

    links.forEach((link) => {
      const isActive = link.dataset.section === activeSectionId;

      if (isActive) {
        link.classList.remove("text-gray-600", "dark:text-slate-400");
        link.classList.add("bg-emerald-50", "text-emerald-700", "font-medium", "dark:bg-emerald-950/40", "dark:text-emerald-300");
      } else {
        link.classList.remove("bg-emerald-50", "text-emerald-700", "font-medium", "dark:bg-emerald-950/40", "dark:text-emerald-300");
        link.classList.add("text-gray-600", "dark:text-slate-400");
      }
    });
  }
}
