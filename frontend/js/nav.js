// Marks the current page in the shared header nav.
const here = location.pathname === "/" ? "/index.html" : location.pathname;
document.querySelectorAll(".nav a").forEach((a) => {
  const target = a.getAttribute("href") === "/" ? "/index.html" : a.getAttribute("href");
  if (target === here || (target === "/index.html" && here === "/report.html")) a.setAttribute("aria-current", "page");
});
