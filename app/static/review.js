'use strict';
// Progressive enhancement for source review, separate from immutable public notices.
document.addEventListener('click', async event => {
  if (!event.target.closest('#review-dossier')) return;
  try {
    const id = location.pathname.split('/').pop();
    const docs = (await api('/documents')).filter(d => d.status === 'READY');
    modal(t("Review tender documentation"), `<p class="subtle">${htmlMessage("Upload the official tender dossier to your private evidence vault first. Link exact requirement text here. Your review is an auditable company overlay; it does not rewrite TED source facts.")}</p><div class="spacer"></div><form id="dossier-form"><div class="field"><label for="review-document">${htmlMessage("Tender document")}</label><select id="review-document" name="document_id" required>${docs.map(d => `<option value="${esc(d.id)}">${esc(d.filename)}</option>`).join('')}</select></div><div id="dossier-preview"></div>${field('source_locator',t("Page / section"))}${area('source_excerpt',t("Exact requirement excerpt (one clause per line)"))}${area('reason',t("Review notes and source completeness justification"))}<div class="field"><label><input type="checkbox" name="complete"> ${htmlMessage("I reviewed the complete dossier and confirm the extracted requirement set is complete for this notice.")}</label></div><p class="source-note">${htmlMessage("Ambiguous clauses remain UNKNOWN. Existing source-extracted gates remain in the assessment; classification corrections are recorded separately.")}</p><button type="submit" class="primary">${htmlMessage("Save reviewed requirements")}</button></form>`);
    const preview = async () => { const doc = $('#review-document').value; $('#dossier-preview').innerHTML = doc ? `<pre class="document-preview" translate="no">${esc((await api('/documents/'+doc)).text)}</pre>` : `<p class="notice">${htmlMessage("Upload a readable tender document in the evidence vault first.")}</p>`; };
    on('#review-document','change',preview); await preview();
    form('#dossier-form',async data => { const body = Object.fromEntries(data); body.complete = data.has('complete'); await api('/opportunities/'+id+'/dossier-review',{method:'POST',body}); $('#modal').close(); await opportunityDetail(id); toast(t("Reviewed requirements saved. Recompute to see the updated assessment.")); });
  } catch (error) { toast(error.message); }
});
const reviewObserver = new MutationObserver(() => {
  if (document.body.dataset.documentProcessing === 'false') return;
  if (!location.pathname.startsWith('/opportunities/') || $('#review-dossier')) return;
  const row = $('.button-row', main);
  if (row) { const button = document.createElement('button'); button.className='secondary'; button.id='review-dossier'; button.textContent=t("Review tender dossier"); row.append(button); }
  if (row && !$('#refresh-source')) { const button=document.createElement('button');button.id='refresh-source';button.className='secondary';button.textContent=t("Fetch official XML");button.addEventListener('click',async()=>{try{const r=await api('/opportunities/'+location.pathname.split('/').pop()+'/refresh-source',{method:'POST'});toast(t('Official XML fetch {0}. Refresh after worker processing.',label(r.status)));}catch(e){toast(e.message);}});row.append(button); }
});
reviewObserver.observe(main,{childList:true,subtree:true});
