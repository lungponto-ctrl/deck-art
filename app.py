import os
import sqlite3
import uuid
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from PIL import Image
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "deckart.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
MARCA_DAGUA_PATH = os.path.join(BASE_DIR, "static", "img", "marca-dagua.png")

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-secreta-deckart-2026")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # Até 50 MB (ideal para vídeos curtos)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "DeckArt@2026")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS depoimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                servico TEXT NOT NULL,
                comentario TEXT NOT NULL,
                imagem TEXT NOT NULL,
                aprovado INTEGER NOT NULL DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS midias_portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                tipo TEXT NOT NULL,
                arquivo TEXT NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


init_db()


def get_ext(filename):
    if not filename or "." not in filename:
        return ""
    return secure_filename(filename).rsplit(".", 1)[1].lower()


def allowed_file(filename, apenas_imagem=False):
    ext = get_ext(filename)
    if apenas_imagem:
        return ext in ALLOWED_IMAGE_EXTENSIONS
    return ext in ALLOWED_EXTENSIONS


def remover_arquivo_upload(nome_arquivo):
    if not nome_arquivo:
        return
    caminho = os.path.join(UPLOAD_FOLDER, nome_arquivo)
    if os.path.exists(caminho):
        os.remove(caminho)


def aplicar_marca_dagua(caminho_imagem, logo_path=MARCA_DAGUA_PATH, opacidade=0.50):
    if not os.path.exists(logo_path):
        return

    try:
        with Image.open(caminho_imagem) as img, Image.open(logo_path) as logo:
            formato_original = img.format or "JPEG"
            base = img.convert("RGBA")

            logo_rgba = logo.convert("RGBA")
            pixels = logo_rgba.getdata()
            novo_logo = []
            for r, g, b, a in pixels:
                brilho = max(r, g, b)
                if brilho < 25 or a == 0:
                    novo_logo.append((255, 255, 255, 0))
                else:
                    alfa_final = int(min(255, (brilho / 255.0) * (a / 255.0) * 255 * opacidade))
                    novo_logo.append((255, 255, 255, alfa_final))
            logo_rgba.putdata(novo_logo)

            bbox_logo = logo_rgba.getbbox()
            if bbox_logo:
                logo_rgba = logo_rgba.crop(bbox_logo)

            largura_alvo = max(100, int(base.width * 0.28))
            proporcao = largura_alvo / float(logo_rgba.width)
            altura_alvo = max(50, int(logo_rgba.height * proporcao))
            logo_redimensionado = logo_rgba.resize(
                (largura_alvo, altura_alvo),
                Image.Resampling.LANCZOS
            )

            camada = Image.new("RGBA", base.size, (255, 255, 255, 0))
            x = (base.width - largura_alvo) // 2
            y = (base.height - altura_alvo) // 2

            camada.paste(logo_redimensionado, (x, y), logo_redimensionado)
            combinada = Image.alpha_composite(base, camada)

            if formato_original.upper() in ("JPG", "JPEG"):
                combinada.convert("RGB").save(caminho_imagem, format="JPEG", quality=90, optimize=True)
            elif formato_original.upper() == "WEBP":
                combinada.save(caminho_imagem, format="WEBP", quality=90)
            else:
                combinada.save(caminho_imagem, format="PNG", optimize=True)
    except Exception as e:
        print(f"Aviso ao aplicar marca d'água com logótipo: {e}")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logado"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    with get_db() as conn:
        depoimentos = conn.execute(
            "SELECT * FROM depoimentos WHERE aprovado = 1 ORDER BY id DESC"
        ).fetchall()
        fotos_extra = conn.execute(
            "SELECT * FROM midias_portfolio WHERE tipo = 'imagem' ORDER BY id DESC"
        ).fetchall()
        videos_extra = conn.execute(
            "SELECT * FROM midias_portfolio WHERE tipo = 'video' ORDER BY id DESC"
        ).fetchall()
    return render_template(
        "index.html",
        depoimentos=depoimentos,
        fotos_extra=fotos_extra,
        videos_extra=videos_extra
    )


@app.route("/enviar-depoimento", methods=["POST"])
def enviar_depoimento():
    nome = request.form.get("nome", "").strip()
    servico = request.form.get("servico", "").strip()
    comentario = request.form.get("comentario", "").strip()
    foto = request.files.get("foto")

    if not nome or not servico or not comentario or not foto or foto.filename == "":
        flash("Preencha todos os campos e selecione uma foto do seu projeto.", "erro")
        return redirect(url_for("index") + "#depoimentos")

    if len(nome) > 80 or len(comentario) > 500:
        flash("Texto muito longo. Resuma seu comentário em até 500 caracteres.", "erro")
        return redirect(url_for("index") + "#depoimentos")

    if not allowed_file(foto.filename, apenas_imagem=True):
        flash("Formato inválido. Envie apenas imagens JPG, PNG ou WEBP.", "erro")
        return redirect(url_for("index") + "#depoimentos")

    ext = get_ext(foto.filename)
    nome_arquivo = f"{uuid.uuid4().hex}.{ext}"
    caminho_arquivo = os.path.join(UPLOAD_FOLDER, nome_arquivo)
    foto.save(caminho_arquivo)
    aplicar_marca_dagua(caminho_arquivo)

    with get_db() as conn:
        conn.execute(
            "INSERT INTO depoimentos (nome, servico, comentario, imagem, aprovado) VALUES (?, ?, ?, ?, 0)",
            (nome, servico, comentario, nome_arquivo)
        )

    flash("Obrigado! Sua foto e comentário foram enviados e aparecerão no site após aprovação.", "sucesso")
    return redirect(url_for("index") + "#depoimentos")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        if usuario == ADMIN_USER and senha == ADMIN_PASSWORD:
            session["admin_logado"] = True
            return redirect(url_for("admin_painel"))
        flash("Usuário ou senha incorretos.", "erro")
    return render_template("admin.html", modo="login")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logado", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_painel():
    with get_db() as conn:
        pendentes = conn.execute(
            "SELECT * FROM depoimentos WHERE aprovado = 0 ORDER BY id DESC"
        ).fetchall()
        aprovados = conn.execute(
            "SELECT * FROM depoimentos WHERE aprovado = 1 ORDER BY id DESC"
        ).fetchall()
        midias = conn.execute(
            "SELECT * FROM midias_portfolio ORDER BY id DESC"
        ).fetchall()
    return render_template(
        "admin.html",
        modo="painel",
        pendentes=pendentes,
        aprovados=aprovados,
        midias=midias
    )


@app.route("/admin/midia/novo", methods=["POST"])
@login_required
def admin_nova_midia():
    titulo = request.form.get("titulo", "").strip()
    descricao = request.form.get("descricao", "").strip()
    arquivo = request.files.get("arquivo")

    if not titulo or not arquivo or arquivo.filename == "":
        flash("Informe um título e selecione uma foto ou vídeo.", "erro")
        return redirect(url_for("admin_painel") + "#midias")

    if len(titulo) > 100 or len(descricao) > 250:
        flash("Título ou descrição muito longos.", "erro")
        return redirect(url_for("admin_painel") + "#midias")

    if not allowed_file(arquivo.filename, apenas_imagem=False):
        flash("Formato não suportado. Use JPG, PNG, WEBP para fotos ou MP4, MOV, WEBM para vídeos.", "erro")
        return redirect(url_for("admin_painel") + "#midias")

    ext = get_ext(arquivo.filename)
    tipo = "imagem" if ext in ALLOWED_IMAGE_EXTENSIONS else "video"
    nome_arquivo = f"{uuid.uuid4().hex}.{ext}"
    caminho_arquivo = os.path.join(UPLOAD_FOLDER, nome_arquivo)
    arquivo.save(caminho_arquivo)

    if tipo == "imagem":
        aplicar_marca_dagua(caminho_arquivo)

    with get_db() as conn:
        conn.execute(
            "INSERT INTO midias_portfolio (titulo, descricao, tipo, arquivo) VALUES (?, ?, ?, ?)",
            (titulo, descricao or "Trabalho executado pela Deck & Art.", tipo, nome_arquivo)
        )

    flash(f"{'Foto' if tipo == 'imagem' else 'Vídeo'} adicionado ao site com sucesso!", "sucesso")
    return redirect(url_for("admin_painel") + "#midias")


@app.route("/admin/midia/excluir/<int:midia_id>", methods=["POST"])
@login_required
def admin_excluir_midia(midia_id):
    with get_db() as conn:
        item = conn.execute("SELECT arquivo FROM midias_portfolio WHERE id = ?", (midia_id,)).fetchone()
        if item:
            remover_arquivo_upload(item["arquivo"])
            conn.execute("DELETE FROM midias_portfolio WHERE id = ?", (midia_id,))
    flash("Item do portfólio removido.", "sucesso")
    return redirect(url_for("admin_painel") + "#midias")


@app.route("/admin/aprovar/<int:item_id>", methods=["POST"])
@login_required
def admin_aprovar(item_id):
    with get_db() as conn:
        conn.execute("UPDATE depoimentos SET aprovado = 1 WHERE id = ?", (item_id,))
    flash("Depoimento aprovado e publicado no site!", "sucesso")
    return redirect(url_for("admin_painel"))


@app.route("/admin/ocultar/<int:item_id>", methods=["POST"])
@login_required
def admin_ocultar(item_id):
    with get_db() as conn:
        conn.execute("UPDATE depoimentos SET aprovado = 0 WHERE id = ?", (item_id,))
    flash("Depoimento movido para pendentes.", "sucesso")
    return redirect(url_for("admin_painel"))


@app.route("/admin/excluir/<int:item_id>", methods=["POST"])
@login_required
def admin_excluir(item_id):
    with get_db() as conn:
        item = conn.execute("SELECT imagem FROM depoimentos WHERE id = ?", (item_id,)).fetchone()
        if item:
            remover_arquivo_upload(item["imagem"])
            conn.execute("DELETE FROM depoimentos WHERE id = ?", (item_id,))
    flash("Item excluído permanentemente.", "sucesso")
    return redirect(url_for("admin_painel"))


if __name__ == "__main__":
    app.run(debug=False)