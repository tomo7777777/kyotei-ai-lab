# 競艇AIラボ

毎朝5時20分にその日の全レースをAIで予想して固定し、日中は展示・オッズ・結果を取り込んで成績を記録します。すべてGitHub Actionsで自動で動きます。

- 画面: `web/`（GitHub Pagesで公開）
- 予想・記録: `data/`（`days/` 日ごとの予想と結果、`records.json` 成績、`racers/` 選手の癖）
- 処理: `scripts/`（`daily.py` 毎日の処理、`train.py` AIの学習、`build_history.py` 過去データ）
- データ: BOAT RACE公式サイト・公式ダウンロードデータ

予想は参考情報で、的中や利益を保証するものではありません。
