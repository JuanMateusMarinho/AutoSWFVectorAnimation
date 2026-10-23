package {
    import flash.display.Sprite;
    import flash.events.MouseEvent;
    import flash.text.TextField;
    import flash.text.TextFieldAutoSize;
    import flash.text.TextFormat;

    /** A button drawn in the stage's AQW-like browns and golds (no Artix art). */
    public class AutoSWFButton extends Sprite {
        public static const BROWN:uint = 0x3B2716;
        public static const DARK:uint = 0x2A1D10;
        public static const GOLD:uint = 0xC9A445;
        public static const CREAM:uint = 0xF3DFAE;

        public var label:TextField;
        private var w:Number;
        private var h:Number;
        private var lit:Boolean = false;

        public function AutoSWFButton(text:String, w:Number, h:Number, onClick:Function, size:int = 11) {
            super();
            this.w = w;
            this.h = h;
            label = AutoSWFButton.text(text, size, CREAM);
            label.x = Math.round((w - label.width) / 2);
            label.y = Math.round((h - label.height) / 2);
            addChild(label);
            draw();
            buttonMode = true;
            mouseChildren = false;
            addEventListener(MouseEvent.CLICK, function (e:MouseEvent):void { onClick(); });
        }

        public function set selected(value:Boolean):void {
            lit = value;
            draw();
        }

        public function setText(text:String):void {
            label.text = text;
            label.x = Math.round((w - label.width) / 2);
        }

        private function draw():void {
            graphics.clear();
            graphics.lineStyle(1, GOLD);
            graphics.beginFill(lit ? GOLD : BROWN, 0.95);
            graphics.drawRoundRect(0, 0, w, h, 6, 6);
            graphics.endFill();
            label.textColor = lit ? DARK : CREAM;
        }

        /** A non-selectable one-line text field. */
        public static function text(value:String, size:int, color:uint, bold:Boolean = false):TextField {
            var t:TextField = new TextField();
            t.defaultTextFormat = new TextFormat("_sans", size, color, bold);
            t.autoSize = TextFieldAutoSize.LEFT;
            t.selectable = false;
            t.mouseEnabled = false;
            t.text = value;
            return t;
        }
    }
}
