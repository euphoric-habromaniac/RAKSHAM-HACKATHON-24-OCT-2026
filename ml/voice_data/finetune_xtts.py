"""Fine-tune the XTTS-v2 GPT on one speaker's clips, low-memory (8-bit AdamW) for an 8 GB GPU.

    python finetune_xtts.py finetune/pranjal10 --epochs 30
Expects <dir>/train_hi.csv, train_en.csv (+ eval_*.csv) in Coqui format: audio_file|text|speaker_name.
Output: <dir>/run/ (checkpoints), config + vocab in <dir>/run/XTTS_v2.0_original_model_files/.
"""
import argparse
import os
import time
from pathlib import Path

import bitsandbytes as bnb
from trainer import Trainer, TrainerArgs

import TTS.tts.layers.xtts.trainer.gpt_trainer as gt
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.configs.xtts_config import XttsAudioConfig
from TTS.tts.datasets import load_tts_samples
from TTS.tts.layers.xtts.trainer.gpt_trainer import GPTArgs, GPTTrainer, GPTTrainerConfig
from TTS.utils.manage import ModelManager


def adamw8bit(name, params, lr, parameters):
    return bnb.optim.AdamW8bit(parameters, lr=lr, betas=tuple(params["betas"]), eps=params["eps"],
                               weight_decay=params["weight_decay"])


gt.get_optimizer = adamw8bit  # GPTTrainer.get_optimizer looks this name up in its module


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", type=Path)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=1)
    ap.add_argument("--lr", type=float, default=1e-5)
    a = ap.parse_args()
    d = a.data_dir.resolve()
    out = d / "run"
    ckpt_dir = out / "XTTS_v2.0_original_model_files"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    base = "https://huggingface.co/coqui/XTTS-v2/resolve/main/"
    files = ["dvae.pth", "mel_stats.pth", "vocab.json", "model.pth", "config.json"]
    missing = [base + f for f in files if not (ckpt_dir / f).is_file()]
    if missing:
        print(" > downloading", [m.rsplit("/", 1)[1] for m in missing])
        ModelManager._download_model_files(missing, str(ckpt_dir), progress_bar=True)

    datasets = [BaseDatasetConfig(formatter="coqui", dataset_name=f"ft_{lang}", path=str(d),
                                  meta_file_train=str(d / f"train_{lang}.csv"),
                                  meta_file_val=str(d / f"eval_{lang}.csv"), language=lang)
                for lang in ("hi", "en") if (d / f"train_{lang}.csv").exists()]

    model_args = GPTArgs(
        max_conditioning_length=132300, min_conditioning_length=66150, debug_loading_failures=False,
        max_wav_length=255995, max_text_length=200,
        mel_norm_file=str(ckpt_dir / "mel_stats.pth"), dvae_checkpoint=str(ckpt_dir / "dvae.pth"),
        xtts_checkpoint=str(ckpt_dir / "model.pth"), tokenizer_file=str(ckpt_dir / "vocab.json"),
        gpt_num_audio_tokens=1026, gpt_start_audio_token=1024, gpt_stop_audio_token=1025,
        gpt_use_masking_gt_prompt_approach=True, gpt_use_perceiver_resampler=True,
    )
    config = GPTTrainerConfig(
        epochs=a.epochs, output_path=str(out), model_args=model_args, run_name="GPT_XTTS_FT",
        project_name="XTTS_trainer", run_description="speaker fine-tune", datasets=datasets,
        dashboard_logger="tensorboard", audio=XttsAudioConfig(sample_rate=22050, dvae_sample_rate=22050, output_sample_rate=24000),
        batch_size=a.batch_size, batch_group_size=48, eval_batch_size=1, num_loader_workers=0,
        eval_split_max_size=256, print_step=5, plot_step=1000, log_model_step=1000,
        save_step=10**9, save_n_checkpoints=1, save_checkpoints=True, print_eval=False,
        optimizer="AdamW", optimizer_wd_only_on_weights=True,
        optimizer_params={"betas": [0.9, 0.96], "eps": 1e-8, "weight_decay": 1e-2},
        lr=a.lr, lr_scheduler="MultiStepLR",
        lr_scheduler_params={"milestones": [10**8], "gamma": 0.5, "last_epoch": -1}, test_sentences=[],
    )
    model = GPTTrainer(config)
    train_samples, eval_samples = load_tts_samples(config, eval_split=True,
                                                   eval_split_max_size=config.eval_split_max_size,
                                                   eval_split_size=config.eval_split_size)
    print(f" > {len(train_samples)} train / {len(eval_samples)} eval samples")
    trainer = Trainer(TrainerArgs(restore_path=None, skip_train_epoch=False, start_with_eval=False,
                                  grad_accum_steps=a.grad_accum), config, output_path=str(out), model=model,
                      train_samples=train_samples, eval_samples=eval_samples)
    t0 = time.time()
    trainer.fit()
    print(f" > TRAINING DONE in {(time.time() - t0) / 60:.1f} min; output {trainer.output_path}")


if __name__ == "__main__":
    main()
