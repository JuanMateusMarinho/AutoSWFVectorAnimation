package {
    import flash.display.MovieClip;

    /** Stands in for AQW's AvatarMC: the armor's head registers its game labels here (addAnimationListener) and finds
     *  the skeleton as mcChar (parent.parent.parent of the head is this avatar). Playing a game label follows the
     *  client's mcSkel.gotoAndPlay: only the first listener runs; when its flag is set and the label is not Idle the
     *  skeleton does not play it. */
    public dynamic class AutoSWFAvatar extends MovieClip {
        public var animEvents:Object = {};
        public var mcChar:AutoSWFSkeleton;
        public var label:String = "";
        /** (message:String):void — told when the armor's code throws. */
        public var onError:Function;

        public function AutoSWFAvatar(slots:Array, tracks:Object) {
            super();
            mcChar = new AutoSWFSkeleton(this, slots, tracks);
            addChild(mcChar);
        }

        public function addAnimationListener(label:String, fn:Function, block:Boolean = false):void {
            var list:Array = animEvents[label] as Array;
            if (list == null) {
                list = [];
                animEvents[label] = list;
            }
            for each (var entry:Array in list) {
                if (entry[0] == fn) return;
            }
            list.push([fn, block]);
        }

        public function removeAnimationListener(label:String, fn:Function):void {
            var list:Array = animEvents[label] as Array;
            if (list == null) return;
            for (var i:int = list.length - 1; i >= 0; i--) {
                if (list[i][0] == fn) list.splice(i, 1);
            }
        }

        public function clearAnimEvents():void {
            animEvents = {};
        }

        public function playLabel(label:String):void {
            this.label = label;
            var list:Array = animEvents[label] as Array;
            if (list != null && list.length > 0) {
                try {
                    (list[0][0] as Function)();
                } catch (e:Error) {
                    if (onError != null) onError(e.message);
                }
                if (list[0][1] && label != "Idle") return;
            }
            mcChar.playLabel(label);
        }
    }
}
