package {
    import flash.display.MovieClip;
    import flash.display.Shape;
    import flash.display.Sprite;
    import flash.events.MouseEvent;
    import flash.geom.Point;
    import flash.text.TextField;

    /** Every animation, grouped (Skills, Movement, Emotes, Weapons, Other), each game label showing the armor animation
     *  it plays, then the armor's own animations by name. Clicking a row plays it. It scrolls with the wheel anywhere
     *  over it, with a scrollbar (drag its thumb, or click above/below it — usable with a pen) and with PageUp/PageDown
     *  (AutoSWFStage passes them on). */
    public class AutoSWFList extends Sprite {
        public static const GROUPS:Array = ["Skills", "Movement", "Emotes", "Weapons", "Other"];
        public static const ROW:int = 18;
        public static const BAR:int = 10;

        /** Row clips in order, each with .kind ("label" | "motion") and .animation. */
        public var rows:Array = [];
        /** The visible part (the rows scroll under it; bounds of the list itself include the hidden rows). */
        public var area:Shape = new Shape();
        public var thumb:Sprite = new Sprite();
        private var content:Sprite = new Sprite();
        private var track:Sprite = new Sprite();
        private var full:Number = 0;
        private var h:Number;
        private var w:Number;
        private var grab:Number = -1;
        private var stageRef:AutoSWFStage;

        public function AutoSWFList(stageRef:AutoSWFStage, w:Number, h:Number) {
            super();
            this.stageRef = stageRef;
            this.w = w;
            this.h = h;
            area.graphics.beginFill(0);
            area.graphics.drawRect(0, 0, w - BAR - 2, h);
            area.graphics.endFill();
            addChild(area);
            addChild(content);
            content.mask = area;
            track.x = w - BAR;
            track.graphics.beginFill(0x000000, 0.35);
            track.graphics.drawRoundRect(0, 0, BAR, h, BAR, BAR);
            track.graphics.endFill();
            track.addEventListener(MouseEvent.MOUSE_DOWN, onTrack);
            addChild(track);
            thumb.x = w - BAR;
            thumb.buttonMode = true;
            thumb.addEventListener(MouseEvent.MOUSE_DOWN, onThumb);
            addChild(thumb);
            addEventListener(MouseEvent.MOUSE_WHEEL, function (e:MouseEvent):void { scroll(-e.delta * ROW); });
        }

        /** Rebuild for a gender (the armor animation names differ per gender). */
        public function fill(gender:String):void {
            while (content.numChildren > 0) content.removeChildAt(0);
            rows = [];
            content.y = 0;
            var y:Number = 0;
            var labels:Array = stageRef.settings.labels as Array;
            for each (var group:String in GROUPS) {
                var first:Boolean = true;
                for each (var row:Object in labels) {
                    if (row.group != group) continue;
                    if (first) y = header(group, y);
                    first = false;
                    var armor:String = row.armor[gender];
                    y = add("label", row.name, armor != null && armor != row.name ? row.name + "  →  " + armor : row.name, y);
                }
            }
            var motions:Array = stageRef.settings.motions[gender] as Array;
            if (motions != null && motions.length > 0) {
                y = header("Armor animations", y);
                for each (var motion:String in motions) y = add("motion", motion, motion, y);
            }
            full = y + 8;
            // a hit area under the headers too, so the wheel works anywhere over the list
            content.graphics.clear();
            content.graphics.beginFill(0, 0);
            content.graphics.drawRect(0, 0, w - BAR - 2, full);
            content.graphics.endFill();
            placeThumb();
        }

        private function header(text:String, y:Number):Number {
            var t:TextField = AutoSWFButton.text(text.toUpperCase(), 10, AutoSWFButton.GOLD, true);
            t.x = 8;
            t.y = y + 6;
            content.addChild(t);
            return y + 24;
        }

        private function add(kind:String, name:String, text:String, y:Number):Number {
            var row:MovieClip = new MovieClip();
            row.y = y;
            row.graphics.beginFill(0, 0);
            row.graphics.drawRect(0, 0, w - BAR - 2, ROW);
            row.graphics.endFill();
            var t:TextField = AutoSWFButton.text(text, 11, AutoSWFButton.CREAM);
            t.x = 12;
            row.addChild(t);
            row.buttonMode = true;
            row.mouseChildren = false;
            row.kind = kind;
            row.animation = name;
            row.addEventListener(MouseEvent.CLICK, function (e:MouseEvent):void {
                if (kind == "motion") stageRef.playMotion(name);
                else stageRef.playGameLabel(name);
            });
            content.addChild(row);
            rows.push(row);
            return y + ROW;
        }

        /** Highlight the row playing (kind and name), none for null. */
        public function highlight(kind:String, name:String):void {
            for each (var row:MovieClip in rows) {
                var on:Boolean = row.kind == kind && row.animation == name;
                row.graphics.clear();
                row.graphics.beginFill(AutoSWFButton.GOLD, on ? 1 : 0);
                row.graphics.drawRect(0, 0, w - BAR - 2, ROW);
                row.graphics.endFill();
                TextField(row.getChildAt(0)).textColor = on ? AutoSWFButton.DARK : AutoSWFButton.CREAM;
            }
        }

        public function scroll(by:Number):void {
            content.y = Math.max(lowest(), Math.min(0, content.y + by));
            placeThumb();
        }

        /** One page down (1) or up (-1). */
        public function page(direction:int):void {
            scroll(-direction * (h - ROW));
        }

        /** Scroll to a fraction of the list: 0 is the top, 1 the end. */
        public function scrollFraction(f:Number):void {
            content.y = Math.max(0, Math.min(1, f)) * lowest();
            placeThumb();
        }

        public function scrollTo(index:int):void {
            var row:MovieClip = rows[index];
            if (row.y + content.y < 0) scroll(-(row.y + content.y));
            else if (row.y + ROW + content.y > h) scroll(h - (row.y + ROW + content.y));
        }

        public function rowVisible(index:int):Boolean {
            var top:Number = rows[index].y + content.y;
            return top >= 0 && top + ROW <= h;
        }

        private function lowest():Number {
            return Math.min(0, h - full);
        }

        private function thumbHeight():Number {
            return full <= h ? h : Math.max(28, h * h / full);
        }

        private function placeThumb():void {
            var th:Number = thumbHeight();
            thumb.graphics.clear();
            thumb.graphics.beginFill(AutoSWFButton.GOLD);
            thumb.graphics.drawRoundRect(0, 0, BAR, th, BAR, BAR);
            thumb.graphics.endFill();
            thumb.y = lowest() == 0 ? 0 : (content.y / lowest()) * (h - th);
            thumb.visible = full > h;
        }

        private function onTrack(e:MouseEvent):void {
            page(e.localY > thumb.y ? 1 : -1);
        }

        private function onThumb(e:MouseEvent):void {
            grab = e.localY;
            stage.addEventListener(MouseEvent.MOUSE_MOVE, onDrag);
            stage.addEventListener(MouseEvent.MOUSE_UP, onDrop);
        }

        private function onDrag(e:MouseEvent):void {
            var y:Number = globalToLocal(new Point(e.stageX, e.stageY)).y - grab;
            scrollFraction(y / Math.max(1, h - thumbHeight()));
        }

        private function onDrop(e:MouseEvent):void {
            stage.removeEventListener(MouseEvent.MOUSE_MOVE, onDrag);
            stage.removeEventListener(MouseEvent.MOUSE_UP, onDrop);
        }
    }
}
