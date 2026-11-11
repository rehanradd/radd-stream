# Manual phone pass checklist — 360px (workspace checks done, real device pass owed)

Automated checks passed (see test_regressions.test_phone_css_checklist
and test_api.test_html_pages_render_with_states):
- [x] CSS: tap targets min-height 44px for buttons, links, tabs, inputs
- [x] CSS: bottom navigation on phone, sidebar on desktop (>=1024px),
      2-column cards at >=768px, 3-column dashboard at >=1280px
- [x] CSS: dark + light via prefers-color-scheme, same tokens both themes
- [x] CSS: tables morph to cards below 768px (no horizontal-scroll-only table)
- [x] HTML: every page has bottom nav + sidebar nav with aria labels,
      labels on login/search/hide inputs, sticky primary action on forms
- [x] HTML: loading skeleton state, empty states with a next action,
      error banner state, all rendered by templates.layout
- [x] Status shown as colour + icon + label together (templates.badge)

NOT done in the workspace, owed at the gate (honest gap, not claimed):
- [ ] Real 360px phone pass, one-handed, dark + light, thumb navigation,
      for every phase screen — needs the owner's device at gate time.
- [ ] Full HTML write forms on every screen: this build ships read-only
      HTML lists + links, a login form, a search form, and a hide form.
      Every other write is complete and tested through the JSON API
      (74 matrix controls), but a phone-only HTML form for approve,
      publish, domain apply, etc. is still owed as polish, not as API.
