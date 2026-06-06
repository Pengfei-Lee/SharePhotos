package com.sharephotos.app;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.google.zxing.BarcodeFormat;
import com.journeyapps.barcodescanner.BarcodeCallback;
import com.journeyapps.barcodescanner.BarcodeResult;
import com.journeyapps.barcodescanner.DecoratedBarcodeView;

import java.util.Collections;
import java.util.List;

public class QRCodeScannerActivity extends Activity {
    public static final String EXTRA_SCAN_RESULT = "picme.scan.result";

    private DecoratedBarcodeView scanner;
    private boolean didScan = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        scanner = new DecoratedBarcodeView(this);
        scanner.setStatusText("");
        scanner.getViewFinder().setVisibility(View.GONE);
        root.addView(scanner, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        root.addView(new ScannerOverlayView(this), new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(20), dp(16), dp(20), dp(12));
        Button close = actionButton("关闭");
        close.setOnClickListener(v -> finish());
        Button manual = actionButton("输入相册码");
        manual.setOnClickListener(v -> finish());
        TextView title = label("扫码加入相册", 18, true);
        title.setGravity(Gravity.CENTER);
        toolbar.addView(close, new LinearLayout.LayoutParams(dp(96), dp(48)));
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(48), 1));
        toolbar.addView(manual, new LinearLayout.LayoutParams(dp(112), dp(48)));
        FrameLayout.LayoutParams toolbarParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(86),
                Gravity.TOP
        );
        root.addView(toolbar, toolbarParams);

        LinearLayout hint = new LinearLayout(this);
        hint.setOrientation(LinearLayout.VERTICAL);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(dp(22), dp(12), dp(22), dp(12));
        hint.setBackground(rounded(Color.argb(150, 0, 0, 0), 32));
        hint.addView(label("扫描 PicMe 相册二维码", 17, true));
        TextView detail = label("支持分享链接和纯相册码", 14, false);
        detail.setTextColor(Color.argb(210, 255, 255, 255));
        hint.addView(detail);
        FrameLayout.LayoutParams hintParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER_HORIZONTAL | Gravity.BOTTOM
        );
        hintParams.bottomMargin = dp(84);
        root.addView(hint, hintParams);

        setContentView(root);
        scanner.getBarcodeView().setDecoderFactory(
                new com.journeyapps.barcodescanner.DefaultDecoderFactory(
                        Collections.singletonList(BarcodeFormat.QR_CODE)
                )
        );
        scanner.decodeContinuous(callback);
    }

    private final BarcodeCallback callback = new BarcodeCallback() {
        @Override
        public void barcodeResult(BarcodeResult result) {
            if (didScan || result == null || result.getText() == null || result.getText().trim().isEmpty()) return;
            didScan = true;
            scanner.pause();
            Intent data = new Intent();
            data.putExtra(EXTRA_SCAN_RESULT, result.getText());
            setResult(RESULT_OK, data);
            finish();
        }

        @Override
        public void possibleResultPoints(List<com.google.zxing.ResultPoint> resultPoints) {}
    };

    @Override
    protected void onResume() {
        super.onResume();
        scanner.resume();
    }

    @Override
    protected void onPause() {
        scanner.pause();
        super.onPause();
    }

    private TextView label(String value, int size, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextColor(Color.WHITE);
        view.setTextSize(size);
        if (bold) view.setTypeface(view.getTypeface(), android.graphics.Typeface.BOLD);
        return view;
    }

    private Button actionButton(String value) {
        Button button = new Button(this);
        button.setText(value);
        button.setTextColor(Color.WHITE);
        button.setTextSize(15);
        button.setAllCaps(false);
        button.setBackground(rounded(Color.argb(120, 0, 0, 0), 28));
        return button;
    }

    private android.graphics.drawable.Drawable rounded(int color, int radiusDp) {
        android.graphics.drawable.GradientDrawable background = new android.graphics.drawable.GradientDrawable();
        background.setColor(color);
        background.setCornerRadius(dp(radiusDp));
        return background;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class ScannerOverlayView extends View {
        private final Paint shade = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint border = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF frame = new RectF();
        private final float density;

        ScannerOverlayView(Activity activity) {
            super(activity);
            density = activity.getResources().getDisplayMetrics().density;
            shade.setColor(Color.argb(72, 0, 0, 0));
            border.setStyle(Paint.Style.STROKE);
            border.setStrokeWidth(3 * density);
            border.setColor(Color.WHITE);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float size = Math.min(getWidth() * 0.68f, 280 * density);
            float left = (getWidth() - size) / 2f;
            float top = (getHeight() - size) / 2f - 12 * density;
            frame.set(left, top, left + size, top + size);
            canvas.drawRect(0, 0, getWidth(), top, shade);
            canvas.drawRect(0, top, left, frame.bottom, shade);
            canvas.drawRect(frame.right, top, getWidth(), frame.bottom, shade);
            canvas.drawRect(0, frame.bottom, getWidth(), getHeight(), shade);
            canvas.drawRoundRect(frame, 28 * density, 28 * density, border);
        }
    }
}
