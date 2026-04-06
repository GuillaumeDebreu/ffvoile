/* ─── VoileCV Frontend ─────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
    // ─── FAQ Accordion ──────────────────────────────────────────
    document.querySelectorAll('.faq-question').forEach(btn => {
        btn.addEventListener('click', () => {
            const item = btn.parentElement;
            const wasOpen = item.classList.contains('open');
            // Close all
            document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));
            // Toggle clicked
            if (!wasOpen) item.classList.add('open');
        });
    });

    // ─── Upload Zone ────────────────────────────────────────────
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('cv-file');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileRemove = document.getElementById('file-remove');
    const payBtn = document.getElementById('pay-btn');
    const emailInput = document.getElementById('email');

    if (!uploadZone) return; // Not on landing page

    let selectedFile = null;

    function updatePayBtn() {
        const hasFile = selectedFile !== null;
        const hasEmail = emailInput.value.includes('@');
        payBtn.disabled = !(hasFile && hasEmail);
    }

    emailInput.addEventListener('input', updatePayBtn);

    // Click to browse
    uploadZone.addEventListener('click', () => fileInput.click());

    // Drag & drop
    uploadZone.addEventListener('dragover', e => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', e => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) handleFile(file);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            alert('Seuls les fichiers PDF sont acceptés.');
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            alert('Fichier trop volumineux (max 5 Mo).');
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        uploadZone.style.display = 'none';
        fileInfo.style.display = 'flex';
        updatePayBtn();
    }

    fileRemove.addEventListener('click', () => {
        selectedFile = null;
        fileInput.value = '';
        uploadZone.style.display = '';
        fileInfo.style.display = 'none';
        updatePayBtn();
    });

    // ─── Payment Flow ───────────────────────────────────────────
    payBtn.addEventListener('click', async () => {
        if (!selectedFile || !emailInput.value.includes('@')) return;

        payBtn.disabled = true;
        payBtn.textContent = 'Envoi en cours...';

        try {
            // 1. Upload CV
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('email', emailInput.value);

            const uploadRes = await fetch('/api/upload-cv', {
                method: 'POST',
                body: formData,
            });

            if (!uploadRes.ok) {
                const err = await uploadRes.json();
                throw new Error(err.detail || 'Erreur upload');
            }

            const { user_id, token } = await uploadRes.json();

            // 2. Create Stripe checkout session
            const checkoutRes = await fetch('/api/create-checkout-session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id, token }),
            });

            if (!checkoutRes.ok) {
                const err = await checkoutRes.json();
                throw new Error(err.detail || 'Erreur paiement');
            }

            const { checkout_url } = await checkoutRes.json();

            // 3. Redirect to Stripe
            if (checkout_url) {
                window.location.href = checkout_url;
            } else {
                // Stripe test mode without real key - redirect to dashboard directly
                window.location.href = `/dashboard?token=${token}`;
            }

        } catch (err) {
            alert('Erreur: ' + err.message);
            payBtn.disabled = false;
            payBtn.textContent = 'Payer 9,99\u20AC et envoyer mon CV';
        }
    });
});
