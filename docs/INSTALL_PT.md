# Instalação definitiva — KDE Dynamic Themes 3.0

Esta versão é voltada principalmente para o Bazzite/KDE do autor. **Não apaga e não migra** a pasta `~/Projects/kde-dynamic-themes`.

## Instalando

1. Salve e extraia `kde-dynamic-themes-v3.0.0.zip` em `~/Downloads`.
2. Feche as versões anteriores do KDE Dynamic Themes.
3. No Konsole, execute:

```bash
cd "$HOME/Downloads/kde-dynamic-themes-v3.0.0"
python3 scripts/install.py
```

4. Abra o menu de aplicativos KDE, procure **KDE Dynamic Themes** e execute. Se o menu ainda não mostrar a entrada, encerre/reabra o menu ou use `~/.local/bin/kde-dynamic-themes`.

O instalador reutiliza as dependências existentes. Não precisa de `sudo` ou `pip`; se uma dependência estiver ausente, ele para e explica qual. O atalho fica registrado para seu usuário, sem modificar o Bazzite imutável.

## Conferência sem modificar temas

```bash
python3 scripts/verify_install.py --doctor
~/.local/bin/kde-dynamic-themes --doctor
```

Os comandos de diagnóstico são somente de leitura. A troca de wallpaper e os ajustes no Plasma/Konsole só ocorrem quando você escolhe explicitamente Apply Theme ou Restore Stable Baseline na janela.

## Estado de recuperação

A baseline configurada permanece intocada na pasta original. Ao restaurar pelo aplicativo, o resultado esperado é fundo preto nos monitores, KDE `SweetAmbarBlue` e Konsole `Vapor`. Se houver erro na recuperação, **não apague o registro de transação**. O programa antigo continua disponível em `~/Projects/kde-dynamic-themes/app/`.

## Atualizações futuras

Uma versão futura ficará em outra pasta `releases/NUMERO`, e somente o atalho `current` apontará para ela após verificação. Isso evita reescrever os arquivos históricos e permite voltar a uma versão anterior.

## Desinstalação

```bash
python3 scripts/uninstall.py
```

Remove somente a integração com o menu, mantendo os arquivos do programa instalado e todos os dados pessoais, para eventual recuperação. Nenhuma configuração do KDE é revertida automaticamente pela desinstalação.

## GitHub

**Não é necessário ter conta no GitHub para instalar ou usar**. O repositório será publicado depois em sua própria conta, seguindo `docs/GITHUB.md`.
